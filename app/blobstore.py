"""Where the Hive keeps its files: a local folder or Ozone.

    STORAGE_ROOT=storage                         local folder (default; relative to the repo)
    STORAGE_ROOT=ofs://ons1/uat/chss/storage     Ozone UAT
    STORAGE_ROOT=ofs://ons1/prd/chss/storage     Ozone PRD

Every file is named by a *key*: a relative path under the root, always with "/",
e.g. "patient_files/P001-20261112T101500Z/P001-pdf-20261112-AB12.pdf". The same key
works on every root, so moving from UAT to PRD is a setting change.

Ozone is reached in-process through pyarrow + libhdfs with the session's Kerberos
ticket (Cloudera renews it). Deletes are permanent: libhdfs never uses the trash,
which is what withdrawal and purge need.
"""

import fnmatch
import io
import os
import posixpath
import shutil
import subprocess
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Optional, Union

from app.errors import AppError, ValidationError
from app.logging_setup import get_logger

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
CHUNK = 8 * 1024 * 1024
READ_BUFFER = 1024 * 1024
PARTIAL = ".part-"


class StorageError(AppError):
    status_code = 503
    code = "storage_error"


@dataclass(frozen=True)
class Entry:
    key: str
    is_dir: bool
    size: int = 0
    modified: Optional[float] = None  # seconds since epoch

    @property
    def name(self) -> str:
        return posixpath.basename(self.key)


def clean_key(key: str) -> str:
    """'a/b/../c' and absolute paths are refused, so a key never leaves the root."""
    raw = str(key or "").replace("\\", "/").strip()
    if raw.startswith("/") or ":" in raw.split("/", 1)[0]:
        raise ValidationError(f"Storage key must be relative: {raw!r}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValidationError(f"Storage key may not contain '..': {raw!r}")
    return "/".join(parts)


def join(*parts: str) -> str:
    return clean_key("/".join(p.strip("/") for p in parts if p))


class Store:
    """Interface shared by both backends. Keys are relative; "" is the root."""

    root: str

    # -- reading -------------------------------------------------------
    def info(self, key: str) -> Optional[Entry]: ...
    def list(self, prefix: str = "", recursive: bool = False) -> Iterator[Entry]: ...
    def open_read(self, key: str) -> BinaryIO: ...

    # -- writing -------------------------------------------------------
    def _open_write_raw(self, key: str) -> BinaryIO: ...
    def makedirs(self, key: str) -> None: ...
    def move(self, source: str, target: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def delete_tree(self, key: str) -> None: ...

    # -- shared helpers -----------------------------------------------
    def exists(self, key: str) -> bool:
        return self.info(key) is not None

    def is_file(self, key: str) -> bool:
        entry = self.info(key)
        return bool(entry and not entry.is_dir)

    def is_dir(self, key: str) -> bool:
        entry = self.info(key)
        return bool(entry and entry.is_dir)

    def size(self, key: str) -> int:
        entry = self.info(key)
        if not entry or entry.is_dir:
            raise FileNotFoundError(key)
        return entry.size

    def open_write(self, key: str, overwrite: bool = True) -> "AtomicWriter":
        """Write to a temporary name and rename at the end, so readers never
        see half a file and a failed write leaves nothing behind. Use it in a
        `with` block, or call close() to keep the file and abort() to drop it."""
        key = clean_key(key)
        if not overwrite and self.exists(key):
            raise FileExistsError(key)
        parent = posixpath.dirname(key)
        if parent:
            self.makedirs(parent)
        partial = join(parent, f"{PARTIAL}{uuid.uuid4().hex}-{posixpath.basename(key)}")
        return AtomicWriter(self, key, partial, self._open_write_raw(partial), overwrite)

    def read_bytes(self, key: str) -> bytes:
        with self.open_read(key) as stream:
            return stream.read()

    def write_bytes(self, key: str, data: bytes, overwrite: bool = True) -> None:
        with self.open_write(key, overwrite) as out:
            out.write(data)

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(key).decode(encoding)

    def write_text(self, key: str, text: str, encoding: str = "utf-8") -> None:
        self.write_bytes(key, text.encode(encoding))

    def write_stream(self, key: str, source: BinaryIO, overwrite: bool = True) -> int:
        """Copy a readable stream (an upload, a Carbon file) in chunks; returns bytes."""
        written = 0
        with self.open_write(key, overwrite) as out:
            while True:
                chunk = source.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
        return written

    def upload(self, local: Path, key: str, overwrite: bool = True) -> int:
        with open(local, "rb") as source:
            return self.write_stream(key, source, overwrite)

    def download(self, key: str, local: Path) -> Path:
        local.parent.mkdir(parents=True, exist_ok=True)
        with self.open_read(key) as source, open(local, "wb") as out:
            shutil.copyfileobj(source, out, CHUNK)
        return local

    def copy(self, source: str, target: str, overwrite: bool = True) -> int:
        with self.open_read(source) as stream:
            return self.write_stream(target, stream, overwrite)

    def iter_files(self, prefix: str = "") -> Iterator[Entry]:
        return (e for e in self.list(prefix, recursive=True) if not e.is_dir)

    @contextmanager
    def local_copy(self, key: str):
        """A real file path for tools that cannot read a stream (e.g. LibreOffice).
        Ozone: a private temporary copy in /tmp (memory-backed on Cloudera),
        deleted on exit. Local: the file itself, read-only by convention."""
        folder = Path(tempfile.mkdtemp(prefix="hive-"))
        try:
            yield self.download(key, folder / posixpath.basename(key))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    @contextmanager
    def local_output(self, key: str, overwrite: bool = True):
        """A temporary path for a tool to write into; uploaded to `key` on success."""
        folder = Path(tempfile.mkdtemp(prefix="hive-"))
        try:
            path = folder / posixpath.basename(key)
            yield path
            if path.exists():
                self.upload(path, key, overwrite)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def _quiet_delete(self, key: str) -> None:
        try:
            self.delete(key)
        except Exception:  # noqa: BLE001
            pass

    def describe(self, key: str = "") -> str:
        """For logs and error messages."""
        return f"{self.root.rstrip('/')}/{clean_key(key)}" if key else self.root


class AtomicWriter(io.RawIOBase):
    def __init__(self, store: Store, key: str, partial: str, stream, overwrite: bool):
        self._store, self._key, self._partial = store, key, partial
        self._stream, self._overwrite, self._done = stream, overwrite, False

    def writable(self):
        return True

    def write(self, data):
        self._stream.write(data)
        return len(data)

    def flush(self):
        try:
            self._stream.flush()
        except Exception:  # noqa: BLE001  (pyarrow streams flush on close)
            pass

    def close(self):
        if self._done:
            return super().close()
        self._done = True
        try:
            self._stream.close()
            if self._overwrite and self._store.is_file(self._key):
                self._store.delete(self._key)
            self._store.move(self._partial, self._key)
        except BaseException:
            self._store._quiet_delete(self._partial)
            raise
        finally:
            super().close()

    def abort(self):
        if self._done:
            return
        self._done = True
        try:
            self._stream.close()
        finally:
            self._store._quiet_delete(self._partial)
            super().close()

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.close()
        else:
            self.abort()
        return False


class LocalStore(Store):
    def __init__(self, root: Path):
        self.base = root.resolve()
        self.root = str(self.base)

    def path(self, key: str) -> Path:
        """Only for the local backend (and tests)."""
        return self.base / clean_key(key) if clean_key(key) else self.base

    def info(self, key: str) -> Optional[Entry]:
        target = self.path(key)
        try:
            stat = target.stat()
        except FileNotFoundError:
            return None
        return Entry(clean_key(key), target.is_dir(), 0 if target.is_dir() else stat.st_size, stat.st_mtime)

    def list(self, prefix: str = "", recursive: bool = False) -> Iterator[Entry]:
        folder = self.path(prefix)
        if not folder.is_dir():
            return iter(())
        found = folder.rglob("*") if recursive else folder.iterdir()

        def entries():
            for item in sorted(found):
                if item.name.startswith(PARTIAL):
                    continue
                key = item.relative_to(self.base).as_posix()
                stat = item.stat()
                yield Entry(key, item.is_dir(), 0 if item.is_dir() else stat.st_size, stat.st_mtime)

        return entries()

    def open_read(self, key: str) -> BinaryIO:
        return open(self.path(key), "rb")

    def _open_write_raw(self, key: str) -> BinaryIO:
        return open(self.path(key), "wb")

    def makedirs(self, key: str) -> None:
        self.path(key).mkdir(parents=True, exist_ok=True)

    def move(self, source: str, target: str) -> None:
        destination = self.path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.path(source), destination)

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def delete_tree(self, key: str) -> None:
        if not clean_key(key):
            raise ValidationError("Refusing to delete the whole storage root")
        shutil.rmtree(self.path(key), ignore_errors=True)

    @contextmanager
    def local_copy(self, key: str):
        yield self.path(key)


def _prepare_jvm() -> None:
    """libhdfs needs the Hadoop/Ozone jars on CLASSPATH; quieten Hadoop's logging."""
    if not os.environ.get("CLASSPATH"):
        for tool in ("hdfs", "hadoop"):
            if shutil.which(tool):
                done = subprocess.run([tool, "classpath", "--glob"], capture_output=True, text=True, timeout=120)
                if done.returncode == 0 and done.stdout.strip():
                    os.environ["CLASSPATH"] = done.stdout.strip().splitlines()[-1]
                    break
        else:
            raise StorageError("Cannot reach Ozone: no 'hdfs' command to find the Hadoop classpath")
    # Cloudera support confirmed the LdapGroupsMapping warnings are harmless.
    os.environ.setdefault("LIBHDFS_OPTS", "-Dhadoop.root.logger=ERROR,console -Xmx1g")


class OzoneStore(Store):
    def __init__(self, uri: str):
        scheme, _, rest = uri.partition("://")
        service, _, base = rest.partition("/")
        if scheme != "ofs" or not service or not base:
            raise ValidationError(f"STORAGE_ROOT must look like ofs://<service>/<volume>/<bucket>/<folder>: {uri!r}")
        self.root = uri.rstrip("/")
        self.service = f"{scheme}://{service}"
        self.base = "/" + base.strip("/")
        self._fs = None
        self._lock = threading.Lock()

    # -- connection ---------------------------------------------------
    def _connect(self, fresh: bool = False):
        with self._lock:
            if self._fs is None or fresh:
                try:
                    from pyarrow import fs as pafs
                except ImportError as exc:
                    raise StorageError("Ozone storage needs pyarrow (pip install pyarrow)") from exc
                _prepare_jvm()
                # pyarrow puts "hdfs://" in front of a host, so connect to the
                # default filesystem and make ofs://<service> the default.
                self._fs = pafs.HadoopFileSystem("default", 0, extra_conf={"fs.defaultFS": self.service})
                log.info("ozone_connected", root=self.root)
            return self._fs

    def _call(self, action, *args):
        """Run one filesystem call; on an authentication hiccup (the Kerberos
        ticket is replaced every ~13 minutes) reconnect once and retry."""
        try:
            return action(self._connect(), *args)
        except FileNotFoundError:
            raise
        except OSError as exc:
            text = str(exc).lower()
            if any(word in text for word in ("kerberos", "gss", "token", "authentic", "ticket")):
                log.warning("ozone_reconnect", reason=str(exc)[:200])
                return action(self._connect(fresh=True), *args)
            raise StorageError(f"Ozone: {str(exc)[:300]}") from exc

    def _path(self, key: str) -> str:
        key = clean_key(key)
        return f"{self.base}/{key}" if key else self.base

    def _key(self, path: str) -> str:
        if "://" in path:  # some clients return ofs://service/volume/... in listings
            path = "/" + path.split("://", 1)[1].partition("/")[2]
        path = "/" + path.lstrip("/")
        return path[len(self.base):].lstrip("/") if path.startswith(self.base) else path.lstrip("/")

    # -- operations ---------------------------------------------------
    def info(self, key: str) -> Optional[Entry]:
        from pyarrow import fs as pafs

        found = self._call(lambda f, p: f.get_file_info(p), self._path(key))
        if found.type == pafs.FileType.NotFound:
            return None
        is_dir = found.type == pafs.FileType.Directory
        modified = found.mtime.timestamp() if found.mtime else None
        return Entry(clean_key(key), is_dir, 0 if is_dir else (found.size or 0), modified)

    def list(self, prefix: str = "", recursive: bool = False) -> Iterator[Entry]:
        from pyarrow import fs as pafs

        selector = pafs.FileSelector(self._path(prefix), allow_not_found=True, recursive=recursive)
        try:
            found = self._call(lambda f, s: f.get_file_info(s), selector)
        except NotADirectoryError:
            found = []  # same as the local backend: a file has no entries
        except StorageError as exc:
            if "not a directory" not in str(exc).lower():
                raise
            found = []

        def entries():
            for item in sorted(found, key=lambda i: i.path):
                if item.base_name.startswith(PARTIAL):
                    continue
                is_dir = item.type == pafs.FileType.Directory
                yield Entry(self._key(item.path), is_dir, 0 if is_dir else (item.size or 0),
                            item.mtime.timestamp() if item.mtime else None)

        return entries()

    def open_read(self, key: str) -> BinaryIO:
        stream = self._call(lambda f, p: f.open_input_file(p), self._path(key))
        return _Readable(stream, posixpath.basename(clean_key(key)))

    def _open_write_raw(self, key: str) -> BinaryIO:
        return self._call(lambda f, p: f.open_output_stream(p), self._path(key))

    def makedirs(self, key: str) -> None:
        self._call(lambda f, p: f.create_dir(p, recursive=True), self._path(key))

    def move(self, source: str, target: str) -> None:
        parent = posixpath.dirname(clean_key(target))
        if parent:
            self.makedirs(parent)
        self._call(lambda f, a, b: f.move(a, b), self._path(source), self._path(target))

    def delete(self, key: str) -> None:
        if self.is_file(key):
            self._call(lambda f, p: f.delete_file(p), self._path(key))

    def delete_tree(self, key: str) -> None:
        if not clean_key(key):
            raise ValidationError("Refusing to delete the whole storage root")
        if self.is_dir(key):
            self._call(lambda f, p: f.delete_dir(p), self._path(key))


class _Readable(io.RawIOBase):
    """pyarrow's file handle wrapped as a normal Python binary file, so code
    that expects open(..., "rb") (PDF, DICOM, image, Excel readers) works."""

    def __init__(self, stream, name: str = ""):
        self._stream = stream
        self.name = name  # some readers (pydicom) look for a file name

    def readable(self):
        return True

    def seekable(self):
        return True

    def readinto(self, buffer):
        data = self._stream.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def read(self, size=-1):
        return self._stream.read() if size is None or size < 0 else self._stream.read(size)

    def seek(self, offset, whence=io.SEEK_SET):
        return self._stream.seek(offset, whence)

    def tell(self):
        return self._stream.tell()

    def close(self):
        if not self.closed:
            self._stream.close()
        super().close()


class SimulatedOzoneStore(OzoneStore):
    """The real OzoneStore code on a local folder through pyarrow's local
    filesystem: STORAGE_ROOT=ofs-sim:///abs/folder. For testing the Ozone code
    path on a laptop; never used on Cloudera."""

    def __init__(self, uri: str):
        folder = uri.split("://", 1)[1]
        if not folder.startswith("/"):
            raise ValidationError("ofs-sim:// needs an absolute folder, e.g. ofs-sim:///tmp/hive-store")
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.root = uri.rstrip("/")
        self.service = "ofs-sim"
        self.base = folder.rstrip("/")
        self._fs = None
        self._lock = threading.Lock()

    def _connect(self, fresh: bool = False):
        with self._lock:
            if self._fs is None:
                from pyarrow import fs as pafs

                self._fs = pafs.LocalFileSystem()
            return self._fs


_store: Optional[Store] = None
_store_root: Optional[str] = None


def storage_root() -> str:
    return (os.environ.get("STORAGE_ROOT") or "storage").strip()


def is_ozone() -> bool:
    return storage_root().startswith(("ofs://", "ofs-sim://"))


def get_store() -> Store:
    """The configured store; rebuilt if STORAGE_ROOT changes (tests)."""
    global _store, _store_root
    root = storage_root()
    if _store is None or root != _store_root:
        if root.startswith("ofs-sim://"):
            _store = SimulatedOzoneStore(root)
        elif root.startswith("ofs://"):
            _store = OzoneStore(root)
        else:
            path = Path(root)
            _store = LocalStore(path if path.is_absolute() else REPO_ROOT / path)
        _store_root = root
    return _store


# ---------------------------------------------------------------------------
# StoragePath: a pathlib-like handle on a key, so code written for local paths
# (path / "x", .exists(), .read_bytes(), .iterdir(), .relative_to(...)) works on
# any store. It deliberately has no __fspath__: builtin open(), shutil and os
# functions refuse it, so nothing can bypass the store and write to the project
# disk by accident. Use the helpers below (move, copy, walk, local_file, ...).
# ---------------------------------------------------------------------------

STORED_PREFIX = "store:"


@dataclass(frozen=True)
class StatResult:
    st_size: int
    st_mtime: float
    st_ctime: float

    @property
    def st_mtime_ns(self) -> int:
        return int(self.st_mtime * 1_000_000_000)


class StoragePath:
    __slots__ = ("key",)

    def __init__(self, key: str = ""):
        object.__setattr__(self, "key", clean_key(key))

    def __setattr__(self, name, value):
        raise AttributeError("StoragePath is immutable")

    @property
    def store(self) -> Store:
        return get_store()

    # -- pure path operations -----------------------------------------
    def __truediv__(self, other) -> "StoragePath":
        other = other.as_posix() if hasattr(other, "as_posix") and not isinstance(other, StoragePath) else str(other)
        return StoragePath(join(self.key, other))

    def __str__(self) -> str:
        return STORED_PREFIX + self.key

    def __repr__(self) -> str:
        return f"StoragePath({self.key!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, StoragePath) and other.key == self.key

    def __hash__(self) -> int:
        return hash(("StoragePath", self.key))

    def __lt__(self, other) -> bool:
        return self.key < other.key

    def as_posix(self) -> str:
        return str(self)

    @property
    def name(self) -> str:
        return posixpath.basename(self.key)

    @property
    def suffix(self) -> str:
        return PurePosix(self.name).suffix

    @property
    def suffixes(self):
        return PurePosix(self.name).suffixes

    @property
    def stem(self) -> str:
        return PurePosix(self.name).stem

    @property
    def parts(self):
        return tuple(self.key.split("/")) if self.key else ()

    @property
    def parent(self) -> "StoragePath":
        return StoragePath(posixpath.dirname(self.key))

    @property
    def parents(self):
        out, current = [], self
        while current.key:
            current = current.parent
            out.append(current)
        return out

    def joinpath(self, *parts) -> "StoragePath":
        result = self
        for part in parts:
            result = result / part
        return result

    def with_name(self, name: str) -> "StoragePath":
        return self.parent / name

    def with_suffix(self, suffix: str) -> "StoragePath":
        return self.parent / (self.stem + suffix)

    def with_stem(self, stem: str) -> "StoragePath":
        return self.parent / (stem + self.suffix)

    def is_relative_to(self, other) -> bool:
        if not isinstance(other, StoragePath):
            return False
        return not other.key or self.key == other.key or self.key.startswith(other.key + "/")

    def relative_to(self, other):
        if not self.is_relative_to(other):
            raise ValueError(f"{self} is not under {other}")
        return PurePosix(self.key[len(other.key):].lstrip("/") or ".")

    def resolve(self, strict: bool = False) -> "StoragePath":
        return self

    def absolute(self) -> "StoragePath":
        return self

    def is_absolute(self) -> bool:
        return True

    def describe(self) -> str:
        return self.store.describe(self.key)

    # -- filesystem operations ----------------------------------------
    def exists(self) -> bool:
        return self.store.exists(self.key)

    def is_file(self) -> bool:
        return self.store.is_file(self.key)

    def is_dir(self) -> bool:
        return self.store.is_dir(self.key)

    def is_symlink(self) -> bool:
        return False

    def stat(self) -> StatResult:
        entry = self.store.info(self.key)
        if entry is None:
            raise FileNotFoundError(str(self))
        moment = entry.modified or 0.0
        return StatResult(entry.size, moment, moment)

    def iterdir(self):
        return (StoragePath(e.key) for e in self.store.list(self.key))

    def glob(self, pattern: str):
        if "/" in pattern or "**" in pattern:
            raise ValueError("StoragePath.glob supports one folder level; use rglob")
        return (StoragePath(e.key) for e in self.store.list(self.key) if fnmatch.fnmatch(e.name, pattern))

    def rglob(self, pattern: str):
        return (StoragePath(e.key) for e in self.store.list(self.key, recursive=True)
                if fnmatch.fnmatch(e.name, pattern))

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        if self.exists():
            if exist_ok and self.is_dir():
                return
            raise FileExistsError(str(self))
        if not parents and self.parent.key and not self.parent.is_dir():
            raise FileNotFoundError(str(self.parent))
        self.store.makedirs(self.key)

    def rmdir(self) -> None:
        if not self.key:
            raise OSError("Refusing to remove the storage root")
        if not self.is_dir():
            raise NotADirectoryError(str(self))
        if any(True for _ in self.store.list(self.key)):
            raise OSError(f"Directory not empty: {self}")
        self.store.delete_tree(self.key)

    def unlink(self, missing_ok: bool = False) -> None:
        if not self.is_file():
            if missing_ok:
                return
            raise FileNotFoundError(str(self))
        self.store.delete(self.key)

    def touch(self, exist_ok: bool = True) -> None:
        if self.exists():
            if not exist_ok:
                raise FileExistsError(str(self))
            self.write_bytes(self.read_bytes())  # refresh the modification time
        else:
            self.write_bytes(b"")

    def open(self, mode: str = "r", encoding: Optional[str] = None, newline: Optional[str] = None,
             errors: Optional[str] = None):
        binary = "b" in mode
        if "r" in mode and "+" not in mode:
            # 1 MB buffer: readers that ask for a few bytes at a time must not
            # turn into one Ozone round trip per call.
            buffered = io.BufferedReader(self.store.open_read(self.key), buffer_size=READ_BUFFER)
            return buffered if binary else io.TextIOWrapper(
                buffered, encoding=encoding or "utf-8", newline=newline, errors=errors)
        if "w" in mode and "+" not in mode:
            raw = self.store.open_write(self.key, overwrite="x" not in mode)
            return raw if binary else _TextWriter(raw, encoding or "utf-8", newline)
        if "x" in mode:
            raw = self.store.open_write(self.key, overwrite=False)
            return raw if binary else _TextWriter(raw, encoding or "utf-8", newline)
        raise ValueError(f"StoragePath.open does not support mode {mode!r} (files are written whole)")

    def read_bytes(self) -> bytes:
        return self.store.read_bytes(self.key)

    def write_bytes(self, data: bytes) -> int:
        self.store.write_bytes(self.key, data)
        return len(data)

    def read_text(self, encoding: Optional[str] = None, errors: Optional[str] = None) -> str:
        return self.read_bytes().decode(encoding or "utf-8", errors or "strict")

    def write_text(self, text: str, encoding: Optional[str] = None, errors: Optional[str] = None,
                   newline: Optional[str] = None) -> int:
        self.write_bytes(text.encode(encoding or "utf-8", errors or "strict"))
        return len(text)

    def replace(self, target) -> "StoragePath":
        return move(self, target)

    def rename(self, target) -> "StoragePath":
        return move(self, target)


class _TextWriter(io.TextIOWrapper):
    def __init__(self, raw: AtomicWriter, encoding: str, newline: Optional[str]):
        self._atomic = raw
        super().__init__(io.BufferedWriter(raw), encoding=encoding, newline=newline)

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.close()
        else:
            self._atomic.abort()
        return False


def PurePosix(value: str):
    from pathlib import PurePosixPath

    return PurePosixPath(value)


AnyPath = Union[Path, StoragePath]


def is_stored(value) -> bool:
    return isinstance(value, StoragePath) or (isinstance(value, str) and value.startswith(STORED_PREFIX))


def stored_path(value) -> StoragePath:
    """'store:patient_files/x.pdf' (what the database and sidecars hold) -> StoragePath."""
    if isinstance(value, StoragePath):
        return value
    text = str(value)
    if not text.startswith(STORED_PREFIX):
        raise ValueError(f"Not a stored path: {text!r}")
    return StoragePath(text[len(STORED_PREFIX):])


def open_file(path: AnyPath, mode: str = "rb", **kwargs):
    """open() for either a local Path or a StoragePath."""
    if isinstance(path, StoragePath):
        return path.open(mode, **kwargs)
    return open(path, mode, **kwargs)


def file_size(path: AnyPath) -> int:
    return path.stat().st_size


def move(source: AnyPath, target: AnyPath) -> AnyPath:
    """shutil.move/os.replace for any mix of local and stored paths; the target
    is overwritten. Stored -> stored is a rename inside the store (instant)."""
    if isinstance(source, StoragePath) and isinstance(target, StoragePath):
        if source == target:
            return target
        store = get_store()
        if store.is_file(target.key):
            store.delete(target.key)
        store.move(source.key, target.key)
        return target
    if isinstance(target, StoragePath):
        get_store().upload(Path(source), target.key)
        Path(source).unlink()
        return target
    if isinstance(source, StoragePath):
        get_store().download(source.key, Path(target))
        get_store().delete(source.key)
        return target
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return target


def copy(source: AnyPath, target: AnyPath) -> AnyPath:
    if isinstance(target, StoragePath):
        if isinstance(source, StoragePath):
            get_store().copy(source.key, target.key)
        else:
            get_store().upload(Path(source), target.key)
        return target
    if isinstance(source, StoragePath):
        get_store().download(source.key, Path(target))
        return target
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(target))
    return target


def copy_tree(source: AnyPath, target: AnyPath) -> int:
    """Copy every file under `source` into `target` (any mix); returns files copied."""
    copied = 0
    for folder, _, files in walk(source):
        for name in files:
            item = folder / name
            relative = item.relative_to(source).as_posix()
            copy(item, target / relative)
            copied += 1
    return copied


def rmtree(path: AnyPath) -> None:
    if isinstance(path, StoragePath):
        if not path.key:
            raise ValidationError("Refusing to delete the whole storage root")
        get_store().delete_tree(path.key)
    else:
        shutil.rmtree(path, ignore_errors=True)


def walk(root: AnyPath, topdown: bool = True):
    """os.walk for either kind of path: yields (folder, dirnames, filenames).
    With topdown=True, removing names from dirnames skips those folders."""
    if not isinstance(root, StoragePath):
        for dirpath, dirnames, filenames in os.walk(root, topdown=topdown):
            yield Path(dirpath), dirnames, filenames
        return
    store = get_store()
    if not store.is_dir(root.key):
        return
    entries = list(store.list(root.key))
    dirnames = [e.name for e in entries if e.is_dir]
    filenames = [e.name for e in entries if not e.is_dir]
    if topdown:
        yield root, dirnames, filenames
    for name in list(dirnames):
        yield from walk(root / name, topdown)
    if not topdown:
        yield root, dirnames, filenames


@contextmanager
def local_file(path: AnyPath):
    """A real file path for libraries and tools that need one. A stored file is
    copied into /tmp (memory on Cloudera) and the copy is deleted on exit."""
    if isinstance(path, StoragePath):
        with get_store().local_copy(path.key) as real:
            yield Path(real)
    else:
        yield Path(path)


@contextmanager
def editable_file(path: AnyPath):
    """A real file a library can change in place; a stored file's changes are
    uploaded back when the block ends without an error."""
    if not isinstance(path, StoragePath):
        yield Path(path)
        return
    store = get_store()
    if isinstance(store, LocalStore):
        yield store.path(path.key)
        return
    folder = Path(tempfile.mkdtemp(prefix="hive-"))
    try:
        local = store.download(path.key, folder / path.name)
        yield local
        store.upload(local, path.key)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def any_path(value) -> AnyPath:
    """A string from a cache key, sidecar or setting -> StoragePath or local Path."""
    if isinstance(value, (StoragePath, Path)):
        return value
    text = str(value)
    return stored_path(text) if text.startswith(STORED_PREFIX) else Path(text)


def stage_input(source: AnyPath, target: Path) -> Path:
    """Put a file at a local path for a separate program (the OCR pipeline):
    a symlink when the store is a local folder, otherwise a copy in /tmp."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(source, StoragePath):
        store = get_store()
        if isinstance(store, LocalStore):
            target.symlink_to(store.path(source.key))
        else:
            store.download(source.key, target)
    else:
        target.symlink_to(Path(source).resolve())
    return target


def work_root() -> Path:
    """Scratch space for files being processed: /tmp (memory on Cloudera),
    never the project disk. HIVE_WORK_DIR overrides it."""
    return Path(os.environ.get("HIVE_WORK_DIR") or Path(tempfile.gettempdir()) / "hive-work")


def write_stream(target: AnyPath, source: BinaryIO) -> int:
    """Copy a readable stream (an upload, a file on the Carbon share) to `target`
    in chunks, without a local copy; the file appears only once complete."""
    if isinstance(target, StoragePath):
        return get_store().write_stream(target.key, source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.part-{uuid.uuid4().hex}")
    written = 0
    try:
        with open(partial, "wb") as out:
            while True:
                chunk = source.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return written
