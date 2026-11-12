from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from app.file_responses import file_response
from pydantic import BaseModel, Field

from app import qc_runs
from app.access_log import READ, record_access
from app.audit import record_audit
from app.schemas import User
from app.security import require_permission

router = APIRouter(prefix="/qc", tags=["qc"])


class QcRule(BaseModel):
    code: str
    severity: str
    text: str


class QcRun(BaseModel):
    name: str
    made_at: str
    run_by: str = ""
    issues: Optional[int] = None
    high: Optional[int] = None
    suppressed: Optional[int] = None
    stale_suppressions: int = 0
    rules: dict = Field(default_factory=dict)
    cohorts: dict = Field(default_factory=dict)


class QcState(BaseModel):
    running: bool = False
    started_at: Optional[str] = None
    run_by: Optional[str] = None
    error: Optional[str] = None


class QcOverview(BaseModel):
    state: QcState
    rules: List[QcRule]
    runs: List[QcRun]


class QcIssues(BaseModel):
    columns: List[str]
    rows: List[List[str]]
    total: int
    page: int
    size: int


class QcSuppression(BaseModel):
    rule: str
    record: str
    reason: str = ""
    by: str = ""
    date: str = ""


class QcSuppress(BaseModel):
    rule: str = Field(min_length=1)
    record: str = Field(min_length=1)
    reason: str = Field(min_length=1)


@router.get("", response_model=QcOverview)
def overview(_actor: User = Depends(require_permission("qc:view"))):
    return {"state": qc_runs.state(), "rules": qc_runs.rules(), "runs": qc_runs.list_runs()}


@router.post("/run", response_model=QcState, status_code=202)
def run(
    background: BackgroundTasks,
    request: Request,
    actor: User = Depends(require_permission("qc:run")),
):
    started = qc_runs.start(actor.username)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="qc_run",
        entity_id=started["started_at"],
        user_id=actor.id,
        old_values=None,
        new_values={"run_by": actor.username},
        request_id=request.headers.get("X-Request-ID"),
    )
    return started


@router.get("/runs/{name}", response_model=QcRun)
def get_run(name: str, _actor: User = Depends(require_permission("qc:view"))):
    return qc_runs.get_run(name)


@router.get("/runs/{name}/issues", response_model=QcIssues)
def run_issues(
    name: str,
    page: int = 1,
    size: int = 50,
    q: str = "",
    rule: str = "",
    cohort: str = "",
    suppressed: bool = False,
    actor: User = Depends(require_permission("qc:view")),
):
    result = qc_runs.issues(name, page, size, q, rule, cohort, suppressed)
    record_access(
        READ, actor=actor, resource_type="qc_report", resource_id=name,
        identified=False, record_count=len(result["rows"]),
        detail="QC issues" + (" (suppressed)" if suppressed else ""),
    )
    return result


@router.get("/runs/{name}/report")
def run_report(
    name: str,
    kind: str = "pdf",
    cohort: Optional[str] = None,
    actor: User = Depends(require_permission("qc:view")),
):
    path = qc_runs.report_file(name, kind, cohort)
    record_access(
        READ, actor=actor, resource_type="qc_report", resource_id=f"{name}/{path.name}",
        identified=False, detail="QC report download",
    )
    media = "application/pdf" if path.suffix == ".pdf" else (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return file_response(path, media_type=media, filename=f"{name}-{path.name}",
                        headers={"Cache-Control": "no-store"})


@router.get("/suppressions", response_model=List[QcSuppression])
def list_suppressions(_actor: User = Depends(require_permission("qc:view"))):
    return qc_runs.suppressions()


@router.post("/suppressions", response_model=QcSuppression, status_code=201)
def add_suppression(
    payload: QcSuppress,
    background: BackgroundTasks,
    request: Request,
    actor: User = Depends(require_permission("qc:run")),
):
    entry = qc_runs.suppress(payload.rule, payload.record, payload.reason, actor.username)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="qc_suppression",
        entity_id=f"{entry['rule']}:{entry['record']}",
        user_id=actor.id,
        old_values=None,
        new_values=entry,
        request_id=request.headers.get("X-Request-ID"),
    )
    return entry


@router.delete("/suppressions", response_model=QcSuppression)
def remove_suppression(
    rule: str,
    record: str,
    background: BackgroundTasks,
    request: Request,
    actor: User = Depends(require_permission("qc:run")),
):
    entry = qc_runs.unsuppress(rule, record)
    background.add_task(
        record_audit,
        action="DELETE",
        entity_type="qc_suppression",
        entity_id=f"{entry['rule']}:{entry['record']}",
        user_id=actor.id,
        old_values=entry,
        new_values=None,
        request_id=request.headers.get("X-Request-ID"),
    )
    return entry
