"""Finding patient codes in a dropped folder, and deciding what to do.

The sending system does not tell us anything. It writes files into a folder
tree, and the only thing tying a document to a person is a code in its path
or its name:

    incoming_data/A/B/C/AA1234/image.dcm
    incoming_data/A/B/C/AA1234/AA1234()_-chest.pdf

So this module answers two questions per file -- what code does it claim,
and can we act on that -- and gives every file exactly one of four
outcomes. Nothing here reads bytes for redaction or moves anything; it only
classifies, so a sweep can be run and read before it is trusted.

**Every outcome is recorded, including the ones we refuse.** A file we
cannot place must be visible and fixable, not skipped into silence: that is
the difference between "1,000 files arrived, 3 need attention" and "997
files arrived".
"""

import hashlib
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from app.deid import DEIDENTIFIABLE_LABEL, is_deidentifiable
from app.filetype import head_of, resolve_extension
from app.ids import is_patient_code, normalise_patient_code
from app.logging_setup import get_logger

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _configured_dir(name: str, default: str) -> Path:
    value = Path(os.environ.get(name, default))
    return value if value.is_absolute() else REPO_ROOT / value


def intake_root() -> Path:
    """Where batches are dropped. One definition, shared with storage's
    allowed roots, so the two can never disagree about where it is."""
    from app.storage import intake_root as storage_intake_root

    return storage_intake_root()


def deidentified_dir_name() -> str:
    return os.environ.get("INTAKE_DEID_DIRNAME", "de_identified")


def deidentified_root(root: Optional[Path] = None) -> Path:
    """The mirror. It lives *inside* the intake root, so one folder holds a
    batch and its redacted twin, and the two trees are trivially comparable.

    Takes the root it belongs to, because a sweep can be pointed at a
    folder other than the configured one -- and mirroring that batch into
    the *configured* root's tree would scatter one batch across two places.
    """
    return (root or intake_root()) / deidentified_dir_name()


DEFAULT_SETTLE_SECONDS = 20.0


def settle_seconds() -> float:
    """How long a file must sit still to count as finished arriving.

    Read per call, like the other settings here: a default argument bound
    at import cannot be changed without a restart, and this is the number
    most likely to need adjusting against a real push.
    """
    raw = os.environ.get("INTAKE_SETTLE_SECONDS")
    try:
        return float(raw) if raw else DEFAULT_SETTLE_SECONDS
    except ValueError:
        return DEFAULT_SETTLE_SECONDS

BATCH_MARKER = os.environ.get("INTAKE_BATCH_MARKER", "batch.done")

# Folders the sweep never descends into: its own output, and its bookkeeping.
RESERVED_DIRS = ("_reports", ".intake")


# --- outcomes ----------------------------------------------------------

QUEUED = "queued"
SKIPPED = "skipped"
CONFLICT = "conflict"
SUPERSEDED = "superseded"

# Work that was refused, and so may come back corrected.
REFUSED_STATUSES = (SKIPPED, CONFLICT)

UNSUPPORTED_FORMAT = "unsupported format"
NO_PATIENT_CODE = "no patient code"
CODE_CONFLICT = "path and file name disagree"

UNSUPPORTED_DETAIL = f"handled: {DEIDENTIFIABLE_LABEL}"


@dataclass
class Detection:
    """What a file claims about who it belongs to."""

    path_code: Optional[str] = None
    name_code: Optional[str] = None

    @property
    def conflicted(self) -> bool:
        return bool(
            self.path_code and self.name_code and self.path_code != self.name_code
        )

    @property
    def code(self) -> Optional[str]:
        """The agreed code, or None when there is none or they disagree.

        Disagreement is deliberately not resolved here. Picking one would
        file a document under a patient it may not belong to, and because
        redaction now happens before anybody looks, nobody would catch it.
        """
        if self.conflicted:
            return None
        return self.path_code or self.name_code


@dataclass
class Candidate:
    """One file the sweep found, and what it decided about it."""

    path: Path
    relative_path: str
    extension: str
    size: int
    status: str
    detection: Detection
    reason: Optional[str] = None
    detail: Optional[str] = None

    @property
    def code(self) -> Optional[str]:
        return self.detection.code

    @property
    def name(self) -> str:
        return self.path.name


# --- finding a code ----------------------------------------------------

# The code must start the name and end on a boundary. Without the boundary,
# `AVDD12005_x.pdf` would quietly truncate to the real-looking `AVDD1200`,
# and `AA1234_scan` would pass as a code outright.
_NAME_HEAD = re.compile(r"^([A-Za-z0-9]+?)(?=[^A-Za-z0-9]|$)")


def code_in_name(name: str) -> Optional[str]:
    """The code a file name claims, if any.

    `AA1234.pdf`, `AA1234_chest.pdf` and `AA1234()_-chest.pdf` all claim
    AA1234. `chest.pdf`, `REPORT_final.pdf` and `AVDD12005_x.pdf` claim
    nothing.
    """
    stem = Path(name).stem
    if not stem:
        return None

    whole = normalise_patient_code(stem)
    if is_patient_code(whole):
        return whole

    head = _NAME_HEAD.match(stem)
    if head is None:
        return None

    candidate = normalise_patient_code(head.group(1))
    return candidate if is_patient_code(candidate) else None


def code_in_path(relative_path: str) -> Optional[str]:
    """The code a folder claims, if any -- the deepest one wins.

    A whole segment has to be a code: `A/B/C/AA1234/x.dcm` claims AA1234,
    and `C` claims nothing. Deepest wins so that a nested regrouping of the
    tree cannot be overridden by something further up.
    """
    segments = Path(relative_path).parts[:-1]

    for segment in reversed(segments):
        candidate = normalise_patient_code(segment)
        if is_patient_code(candidate):
            return candidate
    return None


def detect(relative_path: str) -> Detection:
    return Detection(
        path_code=code_in_path(relative_path),
        name_code=code_in_name(Path(relative_path).name),
    )


# --- is the file finished arriving -------------------------------------


def is_settled(path: Path, limit: Optional[float] = None) -> bool:
    """Whether a file has stopped being written to.

    A sweep that takes a file the moment it appears will redact half of a
    400MB study -- and report success, because half a study is a readable
    file. So it has to have been untouched for `limit` seconds first.
    """
    seconds = settle_seconds() if limit is None else limit

    try:
        stat = path.stat()
    except OSError:
        return False

    if seconds <= 0:
        return True

    return (time.time() - last_touched(stat)) >= seconds


def last_touched(stat) -> float:
    """When a file was last written *or* put where it is.

    The modification time alone lies: `cp -p` and `rsync -t` copy it over
    from the source, so a file that landed a second ago can claim to be
    weeks old -- and be taken while it is still being written. The change
    time is set by the filesystem on every write and rename and cannot be
    carried over by a copy tool, so the later of the two is the truth.
    """
    return max(stat.st_mtime, stat.st_ctime)


def batch_is_marked_done(directory: Path) -> bool:
    """Whether the sender has said it has finished pushing.

    A marker beats any amount of waiting, so when one is present the
    settle wait is skipped entirely.
    """
    return (directory / BATCH_MARKER).is_file()


# --- walking and classifying -------------------------------------------


def _is_reserved(relative: Path) -> bool:
    parts = relative.parts
    return bool(parts) and (
        parts[0] == deidentified_dir_name() or parts[0] in RESERVED_DIRS
    )


WALK_SLACK_SECONDS = 2.0


def walk_folders(root: Optional[Path] = None, since: Optional[float] = None):
    """(folder, its folder time, its file names) for every folder that might
    hold something new -- the one walk everything else is built on.

    Streams, a folder at a time; no list of millions of paths is built.
    Three kinds of folder are never entered: the de-identified mirror (a
    redacted copy of everything -- it would double the walk), the submitted
    folder wherever it is configured, and hidden folders (`.intake`, and
    anything a copy tool is still assembling).

    With `since`, folders unchanged since then are passed over without
    listing their files. Adding, removing or renaming a file changes its
    folder's time, so such a folder has nothing new -- which keeps a
    minute-by-minute check cheap at millions of files. What it cannot see
    is a file overwritten in place; the periodic full sweep
    (INTAKE_FULL_SWEEP_HOURS) catches those.
    """
    from app.storage import submitted_root

    root = root or intake_root()
    if not root.is_dir():
        return

    submitted = submitted_root().resolve()
    top_skip = {deidentified_dir_name(), *RESERVED_DIRS}

    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        at_top = here == root

        keep = []
        for name in sorted(dirnames):
            if name.startswith("."):
                continue
            if at_top and name in top_skip:
                continue
            try:
                if (here / name).resolve().is_relative_to(submitted):
                    continue
            except OSError:
                continue
            keep.append(name)
        dirnames[:] = keep

        try:
            folder_time = last_touched(here.stat())
        except OSError:
            continue
        if since is not None and folder_time <= since - WALK_SLACK_SECONDS:
            continue

        yield here, folder_time, sorted(filenames)


def walk(root: Optional[Path] = None, since: Optional[float] = None) -> Iterator[Path]:
    """Every file that might be new -- see walk_folders."""
    for here, _, names in walk_folders(root, since):
        for name in names:
            # rsync writes `.image.dcm.Xy12Ab` and renames it when done;
            # Finder leaves .DS_Store. Neither is a document.
            if name == BATCH_MARKER or name.startswith("."):
                continue
            path = here / name
            if path.is_file():
                yield path


def checksum(path: Path, chunk: int = 1024 * 1024) -> str:
    """sha256, so a re-pushed folder does not get redacted twice."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                block = handle.read(chunk)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        log.warning("intake_checksum_failed", path=str(path), error=str(exc))
        return ""
    return digest.hexdigest()


def classify(path: Path, root: Optional[Path] = None) -> Candidate:
    """Decide one file's fate without touching it."""
    root = root or intake_root()
    relative = str(path.relative_to(root))

    # By content where the name does not say, because a PACS export is
    # routinely called IM000001 with no extension at all.
    extension = resolve_extension(path.name, head_of(path))
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    detection = detect(relative)

    candidate = Candidate(
        path=path,
        relative_path=relative,
        extension=extension,
        size=size,
        status=QUEUED,
        detection=detection,
    )

    if not is_deidentifiable(extension):
        candidate.status = SKIPPED
        candidate.reason = UNSUPPORTED_FORMAT
        candidate.detail = f"'{extension or 'no extension'}' -- {UNSUPPORTED_DETAIL}"
        return candidate

    if detection.conflicted:
        candidate.status = CONFLICT
        candidate.reason = CODE_CONFLICT
        candidate.detail = (
            f"the path says {detection.path_code}, "
            f"the file name says {detection.name_code}"
        )
        return candidate

    if not detection.code:
        candidate.status = SKIPPED
        candidate.reason = NO_PATIENT_CODE
        candidate.detail = "no code in the path or the file name"
        return candidate

    return candidate


def survey(root: Optional[Path] = None) -> List[Candidate]:
    """Classify everything currently under the intake root."""
    root = root or intake_root()
    return [classify(path, root) for path in walk(root)]


# --- where the redacted copy will go -----------------------------------


def mirrored_dir(relative_path: str, root: Optional[Path] = None) -> Path:
    """The redacted copy's folder: the same tree, under the mirror.

    `A/B/C/AA1234/image.dcm` -> `<root>/de_identified/A/B/C/AA1234/`.
    """
    return deidentified_root(root) / Path(relative_path).parent


# --- recording a sweep -------------------------------------------------


KEEP_CANDIDATES = 2000


@dataclass
class SweepResult:
    """What a sweep found. Counts are exact; `candidates` is a sample.

    A first sweep of a five-million-file folder cannot keep an object per
    file in memory, so only the first KEEP_CANDIDATES are held -- enough for
    a report to show examples of each outcome.
    """

    batch_id: Optional[str]
    candidates: List["Candidate"]
    recorded: int = 0
    already_seen: int = 0
    superseded: int = 0
    retried: int = 0
    counted: Dict[str, int] = field(default_factory=dict)

    def of_status(self, status: str) -> List["Candidate"]:
        return [c for c in self.candidates if c.status == status]

    def count(self, status: str) -> int:
        if self.counted:
            return self.counted.get(status, 0)
        return len(self.of_status(status))

    def note(self, candidate: "Candidate") -> None:
        self.counted[candidate.status] = self.counted.get(candidate.status, 0) + 1
        if len(self.candidates) < KEEP_CANDIDATES:
            self.candidates.append(candidate)

    @property
    def total(self) -> int:
        return sum(self.counted.values()) if self.counted else len(self.candidates)

    @property
    def queued(self) -> List["Candidate"]:
        return self.of_status(QUEUED)

    @property
    def skipped(self) -> List["Candidate"]:
        return self.of_status(SKIPPED)

    @property
    def conflicts(self) -> List["Candidate"]:
        return self.of_status(CONFLICT)


SWEEP_GROUP = 500


def sweep(
    cursor,
    root: Optional[Path] = None,
    dry_run: bool = True,
    touched_since: Optional[float] = None,
    full: bool = True,
) -> SweepResult:
    """Classify what has arrived, and -- unless this is a dry run -- record it.

    Nothing is redacted or moved here. A dry run answers "what would this
    do" against a real folder, which is the only way to trust the code
    detection before it starts deciding which patient a document belongs
    to.

    `touched_since` is when the previous sweep looked. A file touched after
    it was put there again since -- and if it had failed, putting it there
    again is somebody asking for another try. Both sides of that comparison
    are the filesystem's own clock, so a database in another time zone
    cannot make it wrong. With `full=False` only folders changed since then
    are walked at all.

    Built for millions of files: files are handled in groups of
    SWEEP_GROUP, and each group costs one lookup of what is already known,
    one insert and one update -- never a statement per file, and never a
    load of every row already recorded.
    """
    root = root or intake_root()
    result = SweepResult(batch_id=None, candidates=[])
    since = None if full else touched_since

    group: List[Candidate] = []
    state = {"batch": None}
    for path in walk(root, since=since):
        candidate = classify(path, root)
        result.note(candidate)
        if dry_run:
            continue
        group.append(candidate)
        if len(group) >= SWEEP_GROUP:
            _record_group(cursor, root, group, touched_since, result, state)
            group = []
    if group and not dry_run:
        _record_group(cursor, root, group, touched_since, result, state)

    if dry_run:
        log.info(
            "intake_sweep_dry_run",
            root=str(root),
            found=result.total,
            queued=result.count(QUEUED),
            skipped=result.count(SKIPPED),
            conflicts=result.count(CONFLICT),
        )
        return result

    if state["batch"] is not None:
        from app.crud import intake_files as crud

        crud.finish_batch(cursor, state["batch"].id, "swept")

    # The classification counts describe everything walked, new or not --
    # named for what they are, so "3" beside "recorded=0" does not read as
    # three files waiting.
    log.info(
        "intake_sweep_recorded",
        batch_id=result.batch_id,
        root=str(root),
        full=full,
        recorded=result.recorded,
        already_seen=result.already_seen,
        superseded=result.superseded,
        retried=result.retried,
        walked_redactable=result.count(QUEUED),
        walked_skipped=result.count(SKIPPED),
        walked_conflicts=result.count(CONFLICT),
    )
    return result


def _record_group(cursor, root, group, touched_since, result, state) -> None:
    """Record one group of walked files: one lookup, one insert, one update."""
    from app.crud import intake_files as crud

    by_path = crud.find_by_paths(cursor, [str(c.path) for c in group])

    # A file already recorded at this path, the same size, and not touched
    # since the last sweep is simply still there -- a sibling arrived and
    # changed its folder's time. Reading its bytes to prove it would mean
    # re-reading a whole folder every time one file lands in it.
    fresh: List[Candidate] = []
    for candidate in group:
        here = by_path.get(str(candidate.path), [])
        unchanged = any(r.file_size == candidate.size for r in here)
        if here and unchanged and not _pushed_again(candidate.path, touched_since):
            result.already_seen += 1
            continue
        fresh.append(candidate)
    if not fresh:
        return

    digests = {str(c.path): checksum(c.path) for c in fresh}
    by_checksum = crud.find_by_checksums(cursor, [d for d in digests.values() if d])

    new_rows: List[dict] = []
    updates: List[dict] = []
    for candidate in fresh:
        digest = digests[str(candidate.path)]
        seen = by_checksum.get(digest, []) if digest else []

        # The unit of work is a file at a path, not a run of bytes: identical
        # bytes in two patients' folders are two filings, and keying on the
        # checksum alone silently drops the second. Identical bytes at the
        # same absolute path are the same file arriving again.
        here = [r for r in seen if r.source_path == str(candidate.path)]
        if here:
            failed = [r for r in here if r.status == "failed"]
            if failed and _pushed_again(candidate.path, touched_since):
                for record in failed:
                    updates.append(_outcome(record.id, QUEUED, "retried: the file was pushed again"))
                    result.retried += 1
                continue
            result.already_seen += 1
            continue

        # Same bytes somewhere else -- usually the correction loop, since
        # adding a code to a file name changes no bytes -- or different bytes
        # where a failure or refusal was: either way the old outcome now
        # describes a file that is not there, and leaves the lists.
        stale = [r for r in seen if r.status in REFUSED_STATUSES]
        stale += [
            r
            for r in by_path.get(str(candidate.path), [])
            if r.status in REFUSED_STATUSES + ("failed",) and r not in stale
        ]

        row_id = str(uuid.uuid4())
        new_rows.append(
            {
                "id": row_id,
                "source_path": str(candidate.path),
                "relative_path": candidate.relative_path,
                "file_name": candidate.name,
                "file_extension": candidate.extension,
                "file_size": candidate.size,
                "status": candidate.status,
                "checksum": digest,
                "patient_code": candidate.code,
                "path_code": candidate.detection.path_code,
                "name_code": candidate.detection.name_code,
                "reason": candidate.reason,
                "detail": candidate.detail,
            }
        )
        result.recorded += 1

        if candidate.status == QUEUED:
            for old in stale:
                updates.append(
                    _outcome(
                        old.id,
                        SUPERSEDED,
                        f"the same document was accepted as "
                        f"{candidate.relative_path} ({candidate.code})",
                    )
                )
                result.superseded += 1

        # Later files in this same group must see it too.
        if digest:
            by_checksum.setdefault(digest, []).append(_Seen(row_id, str(candidate.path), candidate.status))

    if new_rows:
        if state["batch"] is None:
            state["batch"] = crud.create_batch(cursor, str(root))
            result.batch_id = state["batch"].id
        for row in new_rows:
            row["batch_id"] = state["batch"].id
        crud.create_files(cursor, new_rows)
    if updates:
        crud.apply_results(cursor, updates)


@dataclass
class _Seen:
    """A row recorded earlier in this sweep, in the shape lookups return."""

    id: str
    source_path: str
    status: str


def _outcome(row_id: str, status: str, detail: str) -> dict:
    return {"id": row_id, "status": status, "output_path": None,
            "output_name": None, "detail": detail}


def _pushed_again(path: Path, since: Optional[float]) -> bool:
    if since is None:
        return False
    try:
        return last_touched(path.stat()) > since
    except OSError:
        return False


def retry(cursor, file_id: str):
    """Send a failed file round again, unchanged.

    Most failures need nothing fixed -- a worker killed for memory, a crash
    mid-document -- just another attempt.
    """
    from app.crud import intake_files as crud
    from app.schemas import IntakeFileUpdate

    record = crud.get_file_or_404(cursor, file_id)
    if record.status != "failed":
        raise ValueError(f"'{record.file_name}' has not failed (it is {record.status})")
    if not Path(record.source_path).is_file():
        raise ValueError(
            f"'{record.file_name}' is no longer at {record.source_path}; "
            "push it again instead"
        )
    return crud.update_file(
        cursor, file_id, IntakeFileUpdate(status=QUEUED, detail="retried by hand")
    )


def resolve_conflict(cursor, file_id: str, code: str):
    """Settle a path-vs-name disagreement with the code a person chose.

    Only a code one of the two halves actually claimed is accepted --
    otherwise this becomes a way to file a document under any patient at
    all, which is the opposite of what the conflict list is for.
    """
    from app.crud import intake_files as crud
    from app.schemas import IntakeFileUpdate

    record = crud.get_file_or_404(cursor, file_id)
    chosen = normalise_patient_code(code)

    if record.status != CONFLICT:
        raise ValueError(f"'{record.file_name}' is not in conflict")

    claimed = {c for c in (record.path_code, record.name_code) if c}
    if chosen not in claimed:
        raise ValueError(
            f"{chosen} is not one of the codes on this file "
            f"({', '.join(sorted(claimed)) or 'none'})"
        )

    return crud.update_file(
        cursor,
        file_id,
        IntakeFileUpdate(
            patient_code=chosen,
            status=QUEUED,
            reason=None,
            detail=f"conflict resolved to {chosen}",
        ),
    )


# --- handing files to an application -----------------------------------


def common_folder(paths: List[str]) -> str:
    """The deepest folder every path shares -- a code's "source folder"."""
    if not paths:
        return ""
    parents = [Path(p).parent for p in paths]
    try:
        return os.path.commonpath([str(p) for p in parents])
    except ValueError:  # different drives; only on Windows
        return str(parents[0])


def available_codes(cursor) -> List[dict]:
    """Every code with redacted files nobody has attached yet.

    What the application's patient step picks from. `patient_exists` says
    whether choosing the code selects a patient or creates one.
    """
    from app.crud import intake_files as crud
    from app.crud import patients as patients_crud

    by_code: dict = {}
    for record in crud.list_files(cursor, status="done"):
        if not record.patient_code:
            continue
        entry = by_code.setdefault(
            record.patient_code, {"code": record.patient_code, "paths": []}
        )
        entry["paths"].append(record.source_path)

    codes = []
    for code in sorted(by_code):
        entry = by_code[code]
        codes.append(
            {
                "code": code,
                "files": len(entry["paths"]),
                "folder": common_folder(entry["paths"]),
                "patient_exists": patients_crud.get_patient(cursor, code) is not None,
            }
        )
    return codes


class AttachError(ValueError):
    pass


def attach_to_application(cursor, application, intake_file_ids: List[str]):
    """Put redacted intake files onto an application, originals alongside.

    Both copies stay where they are in the drop tree; the application row
    points at them. They move only when the application is submitted, so an
    abandoned draft does not strand anything.

    Every file is checked before any is attached. A half-attached selection
    is harder to reason about than a refused one.
    """
    from app.crud import intake_files as crud
    from app.crud import patient_application_files as files_crud
    from app.schemas import IntakeFileUpdate, PatientApplicationFileUpdate
    from app.storage import guess_mime_type
    from app.uploads import record_metadata

    code = application.patient_id
    if not intake_file_ids:
        raise AttachError("Choose at least one file to attach")

    records = []
    for file_id in dict.fromkeys(intake_file_ids):
        record = crud.get_file(cursor, file_id)
        if record is None:
            raise AttachError(f"Intake file '{file_id}' not found")
        if record.status == "claimed":
            raise AttachError(
                f"'{record.file_name}' is already attached to another application"
            )
        if record.status != "done":
            raise AttachError(
                f"'{record.file_name}' has not been de-identified "
                f"(it is {record.status})"
            )
        # The code on the document is the only evidence of whose it is.
        # Attaching it to somebody else's application would override that
        # with a click.
        if record.patient_code != code:
            raise AttachError(
                f"'{record.file_name}' belongs to {record.patient_code}, "
                f"not {code}"
            )
        if not record.output_path or not Path(record.output_path).is_file():
            raise AttachError(
                f"The redacted copy of '{record.file_name}' is missing from disk"
            )
        records.append(record)

    attached = []
    for record in records:
        created = files_crud.create_file(
            cursor,
            application_id=application.id,
            original_file_name=record.file_name,
            sanitized_file_name=record.output_name or record.file_name,
            file_extension=record.file_extension,
            mime_type=guess_mime_type(record.file_name, None),
            file_size=record.file_size,
            file_path=record.source_path,
            description=f"from intake: {record.relative_path}",
        )
        created = files_crud.update_file(
            cursor,
            created.id,
            PatientApplicationFileUpdate(
                deid_status="done",
                is_deidentified=True,
                deidentified_file_name=record.output_name,
                de_identified_file_path=record.output_path,
            ),
        )
        record_metadata(cursor, created.id, Path(record.source_path), record.file_extension)

        crud.update_file(
            cursor,
            record.id,
            IntakeFileUpdate(status="claimed", claimed_by_file_id=created.id),
        )
        attached.append(created)

    log.info(
        "intake_files_attached",
        application_id=application.id,
        code=code,
        attached=len(attached),
    )
    return attached


def release_claim(cursor, application_file_id: str) -> bool:
    """Hand an intake file back when its application copy is removed.

    Returns whether the file came from intake -- in which case the caller
    must **not** delete it from disk. Both copies live in the drop tree and
    belong to it: removing a document from a draft means "not in this
    application", not "destroy the original". Deleting them would also leave
    the released row pointing at files that no longer exist.
    """
    from app.crud import intake_files as crud
    from app.schemas import IntakeFileUpdate

    released = False
    for record in crud.list_files(cursor, status="claimed"):
        if record.claimed_by_file_id == application_file_id:
            crud.update_file(
                cursor,
                record.id,
                IntakeFileUpdate(status="done", claimed_by_file_id=None),
            )
            log.info("intake_claim_released", intake_file_id=record.id)
            released = True
    return released


def mark_submitted(cursor, application_file_id: str) -> None:
    """Close the intake row once its files have left the drop tree.

    `submitted`, not released: the copies have moved to the patient's
    submitted folder, so handing the row back to the pool would offer files
    that are no longer where it says. It also keeps the row as the record of
    where the document arrived -- which is what stops a re-pushed folder
    redacting it a second time.
    """
    from app.crud import intake_files as crud
    from app.schemas import IntakeFileUpdate

    for record in crud.list_files(cursor, status="claimed"):
        if record.claimed_by_file_id == application_file_id:
            crud.update_file(cursor, record.id, IntakeFileUpdate(status="submitted"))
