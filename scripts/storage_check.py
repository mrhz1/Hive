"""Check the Hive storage (local folder or Ozone) end to end.

    python scripts/storage_check.py                       # uses STORAGE_ROOT
    STORAGE_ROOT=ofs://ons1/uat/chss/storage python scripts/storage_check.py

Works only inside <root>/_hive_check/<random>/ and deletes that folder at the end.
Prints OK/FAIL and timings, never file contents, so the output is safe to paste back.
"""

import io
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env.local")
except ImportError:
    pass

from app import blobstore  # noqa: E402

problems = []


def step(label, action):
    started = time.perf_counter()
    try:
        detail = action()
        took = time.perf_counter() - started
        print(f"  OK    {label:<38} {took:6.2f}s" + (f"  {detail}" if detail else ""))
        return True
    except Exception as exc:  # noqa: BLE001
        problems.append(label)
        print(f"  FAIL  {label:<38} {type(exc).__name__}: {str(exc)[:300]}")
        return False


def main():
    if "prd" in blobstore.storage_root().lower().split("/"):
        sys.exit("Refusing to run the check on PRD; point STORAGE_ROOT at UAT")
    store = blobstore.get_store()
    base = f"_hive_check/{uuid.uuid4().hex[:8]}"
    print(f"Storage root: {store.root}  ({'Ozone' if blobstore.is_ozone() else 'local folder'})")
    print(f"Test folder:  {base}\n")

    payload = os.urandom(5 * 1024 * 1024)

    def expect(condition, message):
        if not condition:
            raise AssertionError(message)

    step("connect + list root", lambda: f"{sum(1 for _ in store.list(''))} entries")
    step("write small text file", lambda: store.write_text(f"{base}/a/hello.txt", "hello hive\n"))
    step("read it back", lambda: expect(store.read_text(f"{base}/a/hello.txt") == "hello hive\n", "content differs"))
    step("exists / is_file / is_dir", lambda: expect(
        store.is_file(f"{base}/a/hello.txt") and store.is_dir(f"{base}/a") and not store.exists(f"{base}/nope"),
        "wrong answer"))
    step("write 5 MB (streamed)", lambda: store.write_stream(f"{base}/b/big.bin", io.BytesIO(payload)))
    step("size", lambda: expect(store.size(f"{base}/b/big.bin") == len(payload), "size differs"))

    def random_read():
        with store.open_read(f"{base}/b/big.bin") as stream:
            stream.seek(1_000_000)
            expect(stream.read(16) == payload[1_000_000:1_000_016], "bytes differ")

    step("random read (seek)", random_read)
    step("full read matches", lambda: expect(store.read_bytes(f"{base}/b/big.bin") == payload, "content differs"))
    step("move to another folder", lambda: store.move(f"{base}/b/big.bin", f"{base}/c/moved.bin"))
    step("old name gone, new name there", lambda: expect(
        not store.exists(f"{base}/b/big.bin") and store.size(f"{base}/c/moved.bin") == len(payload), "move wrong"))
    step("copy", lambda: store.copy(f"{base}/c/moved.bin", f"{base}/d/copy.bin"))
    step("overwrite existing file", lambda: store.write_text(f"{base}/a/hello.txt", "second\n"))
    step("overwritten content", lambda: expect(store.read_text(f"{base}/a/hello.txt") == "second\n", "old content"))

    def failed_write_leaves_nothing():
        try:
            with store.open_write(f"{base}/e/broken.bin") as out:
                out.write(b"half")
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass
        expect(not store.exists(f"{base}/e/broken.bin"), "half-written file left behind")
        expect(not [e for e in store.list(f"{base}/e") if not e.is_dir], "temporary file left behind")

    step("failed write leaves nothing", failed_write_leaves_nothing)

    def local_copy():
        with store.local_copy(f"{base}/c/moved.bin") as path:
            expect(path.stat().st_size == len(payload), "local copy size differs")
            kept = path
        if blobstore.is_ozone():
            expect(not kept.exists(), "temporary copy not deleted")

    step("temporary local copy (for tools)", local_copy)

    def local_output():
        with store.local_output(f"{base}/f/tool-output.txt") as path:
            path.write_text("made by a tool\n")
        expect(store.read_text(f"{base}/f/tool-output.txt") == "made by a tool\n", "upload failed")

    step("tool output uploaded", local_output)

    def many_small():
        names = [f"{base}/many/file-{n:03d}.txt" for n in range(100)]
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda key: store.write_text(key, key), names))
        found = [e for e in store.list(f"{base}/many") if not e.is_dir]
        expect(len(found) == 100, f"listed {len(found)} of 100")
        return "8 threads"

    started = time.perf_counter()
    if step("write 100 small files in parallel", many_small):
        took = time.perf_counter() - started
        print(f"        → about {100 / took:.0f} small files per second")
    step("recursive listing", lambda: f"{sum(1 for _ in store.iter_files(base))} files")
    step("refuses keys outside the root", lambda: expect(_refuses(store), "unsafe key accepted"))
    step("delete one file", lambda: store.delete(f"{base}/d/copy.bin"))
    step("delete test folder", lambda: store.delete_tree(base))
    step("test folder gone", lambda: expect(not store.exists(base), "still there"))

    print("\nRESULT:", "all checks passed" if not problems else f"{len(problems)} failed: {', '.join(problems)}")
    sys.exit(1 if problems else 0)


def _refuses(store):
    for bad in ("../outside.txt", "/etc/passwd", "a/../../b"):
        try:
            store.write_text(bad, "x")
            return False
        except Exception:  # noqa: BLE001
            pass
    return True


if __name__ == "__main__":
    main()
