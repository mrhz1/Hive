"""Configuration for the de-identification job."""
import os
from dataclasses import dataclass, field
from typing import Dict, List


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


DEFAULT_DET_MODEL = "PP-OCRv6_medium_det"
DEFAULT_REC_MODEL = "PP-OCRv6_medium_rec"

DEFAULT_SPACY_MODEL = "en_core_web_sm"
DEFAULT_TRANSFORMERS_MODEL = "StanfordAIMI/stanford-deidentifier-base"

MODEL_TO_PRESIDIO_ENTITY: Dict[str, str] = {
    "PATIENT": "PERSON",
    "HCW": "PERSON",          # healthcare worker
    "HOSPITAL": "ORGANIZATION",
    "VENDOR": "ORGANIZATION",
    "DATE": "DATE_TIME",
    "PHONE": "PHONE_NUMBER",
    "ID": "ID",
}

DEFAULT_ENTITIES: List[str] = [
    "PERSON",
    "ORGANIZATION",
    "DATE_TIME",
    "PHONE_NUMBER",
    "ID",
    "EMAIL_ADDRESS",
    "US_SSN",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "URL",
    "MEDICAL_LICENSE",
    "US_DRIVER_LICENSE",
    "US_PASSPORT",
    "US_BANK_NUMBER",
    "US_ITIN",
    "CRYPTO",
    "US_ZIP_CODE",
    "STREET_ADDRESS",
    "MRN",
    "AGE",
]


@dataclass
class Config:
    # --- OCR ---
    det_model: str = field(
        default_factory=lambda: os.environ.get("OCR_DET_MODEL", DEFAULT_DET_MODEL)
    )
    rec_model: str = field(
        default_factory=lambda: os.environ.get("OCR_REC_MODEL", DEFAULT_REC_MODEL)
    )
    ocr_lang: str = field(default_factory=lambda: os.environ.get("OCR_LANG", "en"))
    # "cpu" or "gpu:0". Cloudera AI job nodes here are CPU.
    device: str = field(
        default_factory=lambda: os.environ.get("OCR_DEVICE", "cpu")
    )
    dpi: int = field(default_factory=lambda: _env_int("OCR_DPI", 200))
    min_ocr_confidence: float = field(
        default_factory=lambda: _env_float("OCR_MIN_CONFIDENCE", 0.5)
    )
    use_doc_orientation_classify: bool = field(
        default_factory=lambda: _env_bool("OCR_DOC_ORIENTATION", False)
    )
    use_doc_unwarping: bool = field(
        default_factory=lambda: _env_bool("OCR_DOC_UNWARPING", False)
    )
    use_textline_orientation: bool = field(
        default_factory=lambda: _env_bool("OCR_TEXTLINE_ORIENTATION", False)
    )
    enable_mkldnn: bool = field(
        default_factory=lambda: _env_bool("OCR_ENABLE_MKLDNN", False)
    )
    cpu_threads: int = field(default_factory=lambda: _env_int("OCR_CPU_THREADS", 8))

    # --- NLP / PII ---
    spacy_model: str = field(
        default_factory=lambda: os.environ.get("DEID_SPACY_MODEL", DEFAULT_SPACY_MODEL)
    )
    transformers_model: str = field(
        default_factory=lambda: os.environ.get(
            "DEID_TRANSFORMERS_MODEL", DEFAULT_TRANSFORMERS_MODEL
        )
    )
    score_threshold: float = field(
        default_factory=lambda: _env_float("DEID_SCORE_THRESHOLD", 0.35)
    )
    entities: List[str] = field(default_factory=lambda: list(DEFAULT_ENTITIES))

    box_padding: float = field(
        default_factory=lambda: _env_float("DEID_BOX_PADDING", 2.0)
    )
    redaction_fill: str = field(
        default_factory=lambda: os.environ.get("DEID_REDACTION_FILL", "black")
    )
    # Write the extracted (de-identified) text alongside the PDF.
    write_text: bool = field(default_factory=lambda: _env_bool("DEID_WRITE_TEXT", True))
    # Write a JSON report of what was found/redacted.
    write_report: bool = field(
        default_factory=lambda: _env_bool("DEID_WRITE_REPORT", True)
    )
    report_include_values: bool = field(
        default_factory=lambda: _env_bool("DEID_REPORT_INCLUDE_VALUES", False)
    )

    def __post_init__(self):
        env_entities = os.environ.get("DEID_ENTITIES")
        if env_entities:
            self.entities = [e.strip() for e in env_entities.split(",") if e.strip()]


def load_config() -> Config:
    return Config()
