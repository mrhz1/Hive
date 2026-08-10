"""Data that crosses the stage boundary."""
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1


@dataclass
class OcrSpan:
    """One recognised text run and where it sits on the page image."""

    text: str
    confidence: float
    # Axis-aligned bounds in *image pixel* coordinates.
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "x0": round(self.x0, 2),
            "y0": round(self.y0, 2),
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OcrSpan":
        return cls(
            text=data["text"],
            confidence=float(data.get("confidence", 1.0)),
            x0=float(data["x0"]),
            y0=float(data["y0"]),
            x1=float(data["x1"]),
            y1=float(data["y1"]),
        )


@dataclass
class PageSpans:
    page_number: int  # 1-based
    scale: float  # image pixels per PDF point
    spans: List[OcrSpan] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "scale": self.scale,
            "spans": [s.to_dict() for s in self.spans],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PageSpans":
        return cls(
            page_number=int(data["page_number"]),
            scale=float(data["scale"]),
            spans=[OcrSpan.from_dict(s) for s in data.get("spans", [])],
        )


@dataclass
class OcrDocument:
    """Everything the OCR stage learned about one PDF."""

    source_path: str
    dpi: int
    models: Dict[str, str] = field(default_factory=dict)
    pages: List[PageSpans] = field(default_factory=list)
    status: str = "ok"
    error: Optional[str] = None
    duration_seconds: float = 0.0

    @property
    def total_spans(self) -> int:
        return sum(len(p.spans) for p in self.pages)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "source_path": self.source_path,
            "dpi": self.dpi,
            "models": self.models,
            "status": self.status,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "pages": [p.to_dict() for p in self.pages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OcrDocument":
        version = int(data.get("schema_version", 0))
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"OCR handoff schema v{version} is not readable by this build "
                f"(expected v{SCHEMA_VERSION}); the two virtualenvs are out of sync"
            )
        return cls(
            source_path=data["source_path"],
            dpi=int(data["dpi"]),
            models=data.get("models", {}),
            pages=[PageSpans.from_dict(p) for p in data.get("pages", [])],
            status=data.get("status", "ok"),
            error=data.get("error"),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
        )

    def write(self, path: str) -> None:
        """Write the handoff file."""
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, mode=0o700, exist_ok=True)

        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh)

    @classmethod
    def read(cls, path: str) -> "OcrDocument":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


@dataclass
class PiiSpan:
    """A detected entity, in character offsets into the page text."""

    entity_type: str
    start: int
    end: int
    score: float


@dataclass
class RedactionBox:
    x0: float
    y0: float
    x1: float
    y1: float
    entity_type: str
    score: float


@dataclass
class PageText:
    """A page's OCR spans flattened into one string, plus the index that walks character offsets back to the span they came from."""

    text: str
    # (char_start, char_end, span) per OCR span, in text order.
    index: List[Tuple[int, int, OcrSpan]] = field(default_factory=list)


def read_manifest(path: str) -> List[Dict[str, Any]]:
    """Stage inputs travel in a file, not in argv."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"manifest {path} must contain a JSON list")
    return data


def write_manifest(path: str, jobs: List[Dict[str, Any]]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh)
