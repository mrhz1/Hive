"""Per-document / per-page results.

Separate from the stage modules because both the NLP stage (which
produces them) and the orchestrator (which merges and summarises them
across two subprocesses) need the shape, and the orchestrator runs under
an interpreter that has none of the ML stack installed. Standard library
only, for the same reason as deid/spans.py.
"""
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass
class PageResult:
    page_number: int
    ocr_spans: int
    entities_found: int
    boxes_applied: int
    entity_counts: Dict[str, int] = field(default_factory=dict)
    # Populated only when config.report_include_values is on.
    entity_values: List[dict] = field(default_factory=list)


@dataclass
class DocumentResult:
    source_path: str
    output_pdf: Optional[str] = None
    output_text: Optional[str] = None
    output_report: Optional[str] = None
    pages: List[PageResult] = field(default_factory=list)
    duration_seconds: float = 0.0
    status: str = "ok"
    error: Optional[str] = None
    # Which stage failed, when one did. A caller reading the summary
    # needs to know whether to look at the OCR venv or the NLP venv.
    failed_stage: Optional[str] = None

    @property
    def total_entities(self) -> int:
        return sum(p.entities_found for p in self.pages)

    @property
    def total_boxes(self) -> int:
        return sum(p.boxes_applied for p in self.pages)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["total_entities"] = self.total_entities
        data["total_boxes"] = self.total_boxes
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentResult":
        return cls(
            source_path=data["source_path"],
            output_pdf=data.get("output_pdf"),
            output_text=data.get("output_text"),
            output_report=data.get("output_report"),
            pages=[PageResult(**p) for p in data.get("pages", [])],
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            status=data.get("status", "ok"),
            error=data.get("error"),
            failed_stage=data.get("failed_stage"),
        )


def summarise(results: List[DocumentResult]) -> dict:
    """The JSON the job prints on stdout for its caller to parse."""
    ok = [r for r in results if r.status == "ok"]
    failed = [r for r in results if r.status != "ok"]

    return {
        "files_total": len(results),
        "files_ok": len(ok),
        "files_failed": len(failed),
        "entities_redacted": sum(r.total_entities for r in ok),
        "boxes_applied": sum(r.total_boxes for r in ok),
        "outputs": [
            {"source": r.source_path, "output_pdf": r.output_pdf} for r in ok
        ],
        "failures": [
            {"path": r.source_path, "stage": r.failed_stage, "error": r.error}
            for r in failed
        ],
    }


def exit_code(results: List[DocumentResult]) -> int:
    """0 all succeeded, 1 everything failed, 2 partial failure."""
    if not results:
        return 1
    failed = [r for r in results if r.status != "ok"]
    if not failed:
        return 0
    return 1 if len(failed) == len(results) else 2
