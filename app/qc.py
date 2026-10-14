import csv
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from app import consent, document_info, reports
from app.logging_setup import get_logger
from app.mailer import send_email
from app.migration_report import _rows
from app.storage import REPO_ROOT

log = get_logger(__name__)

HIGH, MEDIUM = "high", "medium"
SUBMITTED = ("submitted", "approved")
MAX_AGE = 100
PDF_ISSUES = 300


@dataclass(frozen=True)
class Rule:
    code: str
    severity: str
    text: str


RULES = {r.code: r for r in [
    Rule("P01", HIGH, "Date of birth missing"),
    Rule("P02", HIGH, "Date of death before date of birth"),
    Rule("P03", HIGH, "Registration before date of birth"),
    Rule("P04", MEDIUM, "Date of death before registration"),
    Rule("P05", MEDIUM, "Date in the future"),
    Rule("P06", MEDIUM, f"Age at registration over {MAX_AGE}"),
    Rule("P07", HIGH, "No name or email (and the site shares records)"),
    Rule("A01", HIGH, "Submitted application without documents"),
    Rule("A02", MEDIUM, "Submitted application without a checklist on record"),
    Rule("D01", MEDIUM, "Document type UNKNOWN"),
    Rule("D02", MEDIUM, "Document date UNKNOWN"),
    Rule("D03", HIGH, "Document dated before the patient's birth"),
    Rule("D04", MEDIUM, "Document dated after the patient's death"),
    Rule("D05", MEDIUM, "Document dated in the future"),
    Rule("D06", HIGH, "De-identification failed on a submitted document"),
    Rule("C01", MEDIUM, "Submitted data but no research consent on record"),
    Rule("C02", HIGH, "Research consent refused or withdrawn, but in an active project"),
]}

COLUMNS = ["rule", "severity", "problem", "record", "patient", "detail"]


@dataclass
class Issue:
    rule: str
    record: str
    patient: str
    detail: str = ""

    def row(self, extra: Tuple = ()) -> list:
        rule = RULES[self.rule]
        return [rule.code, rule.severity, rule.text, self.record, self.patient, self.detail, *extra]


def suppressions_file() -> Path:
    value = Path(os.environ.get("QC_SUPPRESSIONS_FILE", "storage/qc/suppressions.csv"))
    return value if value.is_absolute() else REPO_ROOT / value


def load_suppressions(path: Optional[Path] = None) -> Dict[Tuple[str, str], dict]:
    path = path or suppressions_file()
    if not path.is_file():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for line in csv.DictReader(handle):
            line = {(k or "").strip().lower(): (v or "").strip() for k, v in line.items()}
            if line.get("rule") and line.get("record") and line.get("reason"):
                out[(line["rule"].upper(), line["record"])] = line
            elif any(line.values()):
                log.warning("qc_suppression_ignored", rule=line.get("rule"), record=line.get("record"))
    return out


def _day(value) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _doc_day(name: str) -> Optional[date]:
    parts = document_info.parse_name(name or "") or {}
    day = parts.get("day") or ""
    if not day.isdigit():
        return None
    try:
        return date(int(day[:4]), int(day[4:6]), int(day[6:]))
    except ValueError:
        return None


def check(cursor, today: Optional[date] = None) -> List[Issue]:
    today = today or date.today()
    issues: List[Issue] = []
    add = lambda rule, record, patient, detail="": issues.append(
        Issue(rule, record, patient, detail)
    )

    patients = {}
    for code, birth, registered, death, first, last, email, no_records in _rows(
        cursor,
        "SELECT `id`, `dt_b`, `dt_reg`, `dt_d`, `fstname`, `lstname`, `ptemail`, "
        "`no_records` FROM `patient`",
    ):
        birth, registered, death = _day(birth), _day(registered), _day(death)
        patients[code] = (birth, death)
        if no_records:
            continue
        if not birth:
            add("P01", code, code)
        if not (first or last or email):
            add("P07", code, code)
        if birth and death and death < birth:
            add("P02", code, code, f"born {birth}, died {death}")
        if birth and registered and registered < birth:
            add("P03", code, code, f"born {birth}, registered {registered}")
        if registered and death and death < registered:
            add("P04", code, code, f"registered {registered}, died {death}")
        future = [label for label, day in (("birth", birth), ("registration", registered),
                                           ("death", death)) if day and day > today]
        if future:
            add("P05", code, code, ", ".join(future))
        if birth and registered:
            age = registered.year - birth.year - (
                (registered.month, registered.day) < (birth.month, birth.day))
            if age > MAX_AGE:
                add("P06", code, code, f"{age} years")

    submitted: Dict[str, str] = {}
    checklists: Dict[str, bool] = {}
    for app_id, code, status, checklist in _rows(
        cursor, "SELECT `id`, `patient_id`, `status`, `checklist` FROM `patient_applications`"
    ):
        if status in SUBMITTED:
            submitted[app_id] = code
            checklists[app_id] = bool(checklist)

    documents: Dict[str, int] = defaultdict(int)
    for file_id, app_id, name, deid_status, review in _rows(
        cursor,
        "SELECT `id`, `application_id`, `deidentified_file_name`, `deid_status`, "
        "`review_status` FROM `patient_application_files`",
    ):
        code = submitted.get(app_id)
        if code is None or review == "deleted":
            continue
        documents[app_id] += 1
        if deid_status == "failed":
            add("D06", file_id, code, name or "")
            continue
        parts = document_info.parse_name(name or "") or {}
        if (parts.get("modality") or document_info.UNKNOWN) == document_info.UNKNOWN:
            add("D01", file_id, code, name or "")
        if (parts.get("day") or document_info.UNKNOWN) == document_info.UNKNOWN:
            add("D02", file_id, code, name or "")
        day = _doc_day(name)
        birth, death = patients.get(code, (None, None))
        if day and birth and day < birth:
            add("D03", file_id, code, f"{name}: born {birth}")
        if day and death and day > death:
            add("D04", file_id, code, f"{name}: died {death}")
        if day and day > today:
            add("D05", file_id, code, name or "")

    for app_id, code in submitted.items():
        if not documents.get(app_id):
            add("A01", app_id, code)
        if not checklists.get(app_id):
            add("A02", app_id, code)

    matrix = consent.latest(cursor)
    for code in sorted(set(submitted.values())):
        if "research" not in matrix.get(code, {}):
            add("C01", code, code)

    active = {
        project_id: short_code
        for project_id, short_code, status in _rows(
            cursor, "SELECT `id`, `short_code`, `status` FROM `projects`"
        )
        if status != "ended"
    }
    for project_id, code in _rows(cursor, "SELECT `project_id`, `patient_id` FROM `project_patients`"):
        research = matrix.get(code, {}).get("research")
        if project_id in active and research and research.status in consent.BLOCKING:
            add("C02", f"{active[project_id]}:{code}", code, f"consent {research.status}")

    return issues


def _pdf(path: Path, summary: List[tuple], issues: List[Issue], total: int) -> None:
    import fitz

    doc = fitz.open()
    lines = [("CHSS data quality report", 14), (f"Made {datetime.now():%Y-%m-%d %H:%M}", 9), ("", 9)]
    lines += [(f"{s[0]:<10} {s[1]:<62} {s[2]:>8}", 9) for s in summary]
    lines += [("", 9), (f"Issues ({min(total, PDF_ISSUES)} of {total} shown; all are in issues.csv)", 11)]
    lines += [
        (f"{i.rule}  {i.patient:<12} {i.record[:36]:<36} {i.detail[:60]}", 8)
        for i in issues[:PDF_ISSUES]
    ]
    page, y = None, 0.0
    for text, size in lines:
        if page is None or y > 800:
            page, y = doc.new_page(width=595, height=842), 40.0
        page.insert_text((36, y), text, fontsize=size, fontname="cour")
        y += size + 4
    doc.save(str(path))
    doc.close()


def run(cursor, root: Optional[Path] = None, email: bool = True,
        cap: int = reports.DEFAULT_CAP, today: Optional[date] = None) -> Path:
    found = check(cursor, today)
    suppressed_by = load_suppressions()
    folder = reports.new_folder("qc", root)
    issues_out = reports.ListOut(folder, "issues", "Issues", COLUMNS, cap)
    suppressed_out = reports.ListOut(
        folder, "suppressed", "Suppressed", COLUMNS + ["reason", "by", "date"], cap
    )

    open_issues: List[Issue] = []
    counts: Counter = Counter()
    muted: Counter = Counter()
    used: Set[Tuple[str, str]] = set()
    for issue in sorted(found, key=lambda i: (RULES[i.rule].severity != HIGH, i.rule, i.patient)):
        key = (issue.rule, issue.record)
        if key in suppressed_by:
            line = suppressed_by[key]
            used.add(key)
            muted[issue.rule] += 1
            suppressed_out.add(issue.row((line["reason"], line.get("by", ""), line.get("date", ""))))
            continue
        counts[issue.rule] += 1
        open_issues.append(issue)
        issues_out.add(issue.row())

    summary = [
        (rule.code, f"[{rule.severity}] {rule.text}", counts.get(code, 0))
        for code, rule in RULES.items()
    ]
    summary += [("Suppressed", "Checked and accepted (see Suppressed)", sum(muted.values()))]
    stale = len(set(suppressed_by) - used)
    if stale:
        summary += [("Suppressed", "Suppressions that no longer match an issue", stale)]

    issues_out.close()
    suppressed_out.close()
    path = reports.write_workbook(
        folder / "qc-report.xlsx", "CHSS data quality report", summary, [issues_out, suppressed_out]
    )
    _pdf(folder / "qc-report.pdf", summary, open_issues, len(open_issues))

    high = sum(n for code, n in counts.items() if RULES[code].severity == HIGH)
    if email:
        body = "\n".join(
            [f"The data quality check found {len(open_issues)} issue(s), {high} of them high.", ""]
            + [f"{code}  {text:<70} {n}" for code, text, n in summary if n]
            + ["", f"The report (which patients and records) is in {folder}."]
        )
        send_email(
            [a.strip() for a in os.environ.get("QC_EMAIL_TO", "").split(",")],
            f"Hive data quality: {len(open_issues)} issue(s), {high} high",
            body,
        )
    log.info("qc_report_written", folder=str(folder), issues=len(open_issues), high=high,
             suppressed=sum(muted.values()))
    return path
