import os
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

from app import consent, document_info, intake, reports
from app.db import execute
from app.logging_setup import get_logger

log = get_logger(__name__)

FETCH = 10_000
IMAGE_SUFFIXES = (".dcm", ".dicom")


def _files(root: Path) -> Iterator[Tuple[str, str]]:
    if not root.is_dir():
        return
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            elif not intake.is_extra_file(entry.name):
                yield Path(entry.path).relative_to(root).as_posix(), entry.name


def _rows(cursor, sql: str) -> Iterator[tuple]:
    execute(cursor, sql)
    fetchmany = getattr(cursor, "fetchmany", None)
    if fetchmany is None:
        yield from cursor.fetchall()
        return
    while True:
        batch = fetchmany(FETCH)
        if not batch:
            return
        yield from batch


def _scan_redacted(root: Path, where: str, unknown, counts: Counter) -> int:
    total = 0
    for relative, name in _files(root):
        total += 1
        parts = document_info.parse_name(name) or {}
        kind = parts.get("modality") or document_info.UNKNOWN
        day = parts.get("day") or document_info.UNKNOWN
        counts[f"type {kind}"] += 1
        if kind == document_info.UNKNOWN or day == document_info.UNKNOWN:
            code = relative.split("/", 1)[0]
            missing = " and ".join(
                label for label, value in (("type", kind), ("date", day))
                if value == document_info.UNKNOWN
            )
            unknown.add([where, code, name, missing])
    return total


def build(cursor, root: Optional[Path] = None, cap: int = reports.DEFAULT_CAP) -> Path:
    folder = reports.new_folder("migration", root)
    lists = {
        "failed": reports.ListOut(folder, "failed", "Failed", ["file", "reason", "detail", "code"], cap),
        "attention": reports.ListOut(folder, "needs_attention", "Needs attention", ["file", "reason", "detail", "codes"], cap),
        "unknown": reports.ListOut(folder, "unknown_type_or_date", "Unknown type or date", ["where", "code", "file", "missing"], cap),
        "covered": reports.ListOut(folder, "covered_text_images", "Covered text in images", ["code", "file", "areas covered", "file_id"], cap),
        "leaded": reports.ListOut(folder, "leaded_images", "Leaded images", ["code", "file", "file_id"], cap),
        "unchecked": reports.ListOut(folder, "patients_not_checked", "Patients not checked", ["code"], cap),
        "no_consent": reports.ListOut(folder, "patients_without_consent", "No consent on record", ["code"], cap),
    }
    summary = []

    waiting = sum(1 for _ in _files(intake.intake_root()))
    types: Counter = Counter()
    pending = _scan_redacted(intake.deidentified_root(), "pending", lists["unknown"], types)
    submitted = _scan_redacted(
        intake.submitted_data_root() / "de_identified", "submitted", lists["unknown"], types
    )
    problems = {}
    for kind, key in (("failed", "failed"), ("attention", "attention")):
        reasons: Counter = Counter()
        for item in intake.list_problem_files(kind):
            reasons[item.get("reason") or "unknown"] += 1
            codes = ", ".join(sorted(intake.file_codes(item)))
            lists[key].add([item["path"], item.get("reason"), item.get("detail"), codes])
        problems[kind] = reasons

    done = pending + submitted
    failed = sum(problems["failed"].values())
    attention = sum(problems["attention"].values())
    summary += [
        ("Files", "Waiting in the incoming folder", waiting),
        ("Files", "De-identified, not submitted yet", pending),
        ("Files", "De-identified, submitted", submitted),
        ("Files", "Failed", failed),
        ("Files", "Needs attention", attention),
        ("Files", "Total seen (all of the above)", waiting + done + failed + attention),
        ("Files", "Type or date UNKNOWN", lists["unknown"].count),
    ]
    summary += [("Failed", reason, n) for reason, n in problems["failed"].most_common()]
    summary += [("Needs attention", reason, n) for reason, n in problems["attention"].most_common()]
    summary += [("Document types", label[5:], n) for label, n in sorted(types.items())]

    owner: Dict[str, str] = {}
    statuses: Counter = Counter()
    for app_id, patient_id, status in _rows(
        cursor, "SELECT `id`, `patient_id`, `status` FROM `patient_applications`"
    ):
        owner[app_id] = patient_id
        statuses[status or "unknown"] += 1
    summary += [("Applications", status, n) for status, n in statuses.most_common()]

    documents: Counter = Counter()
    for file_id, app_id, name, deid_status, review, boxes, leaded in _rows(
        cursor,
        "SELECT `id`, `application_id`, `deidentified_file_name`, `deid_status`, "
        "`review_status`, `redaction_boxes`, `leaded_phi` FROM `patient_application_files`",
    ):
        if review == "deleted":
            documents["deleted"] += 1
            continue
        documents["in applications"] += 1
        documents[f"de-identification {deid_status or 'unknown'}"] += 1
        if review == "rejected":
            documents["waiting in Rejections"] += 1
        code = owner.get(app_id, "")
        is_image = (name or "").lower().endswith(IMAGE_SUFFIXES)
        if is_image and boxes not in (None, "") and int(boxes) > 0:
            documents["images with covered text"] += 1
            lists["covered"].add([code, name, int(boxes), file_id])
        if leaded:
            documents["leaded images"] += 1
            lists["leaded"].add([code, name, file_id])
    summary += [("Documents in applications", label, n) for label, n in sorted(documents.items())]

    patients: Counter = Counter()
    codes = []
    for code, checked_at, no_records in _rows(
        cursor, "SELECT `id`, `details_checked_at`, `no_records` FROM `patient`"
    ):
        codes.append(code)
        patients["total"] += 1
        if no_records:
            patients["site shares no records"] += 1
        elif not checked_at:
            patients["details not checked"] += 1
            lists["unchecked"].add([code])
    matrix = consent.latest(cursor)
    for code in codes:
        research = matrix.get(code, {}).get("research")
        if research is None:
            patients["no research consent on record"] += 1
            lists["no_consent"].add([code])
        elif research.status in consent.BLOCKING:
            patients[f"research consent {research.status}"] += 1
    summary += [("Patients", label, n) for label, n in sorted(patients.items())]

    for out in lists.values():
        out.close()
    path = reports.write_workbook(
        folder / "migration-report.xlsx", "Migration report", summary, list(lists.values())
    )
    log.info(
        "migration_report_written",
        folder=str(folder),
        waiting=waiting,
        done=done,
        failed=failed,
        attention=attention,
    )
    return path
