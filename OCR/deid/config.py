"""Configuration for the de-identification job.

Everything is driven by env vars with sane defaults, matching the pattern
used by the Hive/FastAPI side of this repo: no code branches on
environment, only values change between local and Cloudera AI.

Model identifiers are pinned here rather than scattered through the code
so a model swap is a one-line change.
"""
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


# PP-OCRv6 tiers: tiny (1.5M) / small / medium (34.5M). medium is the
# accuracy pick and still small enough for CPU; drop to small/tiny if job
# wall-time matters more than recall.
DEFAULT_DET_MODEL = "PP-OCRv6_medium_det"
DEFAULT_REC_MODEL = "PP-OCRv6_medium_rec"

# spaCy handles tokenization/lemmatization only -- NER comes from the
# transformers model below.
DEFAULT_SPACY_MODEL = "en_core_web_sm"
DEFAULT_TRANSFORMERS_MODEL = "StanfordAIMI/stanford-deidentifier-base"

# stanford-deidentifier-base emits: O, VENDOR, DATE, HCW, HOSPITAL, ID,
# PATIENT, PHONE (verified against the model's config.json id2label).
# Note it has NO location/address label -- see recognizers.py, which adds
# pattern recognizers to cover that gap.
MODEL_TO_PRESIDIO_ENTITY: Dict[str, str] = {
    "PATIENT": "PERSON",
    "HCW": "PERSON",          # healthcare worker
    "HOSPITAL": "ORGANIZATION",
    "VENDOR": "ORGANIZATION",
    "DATE": "DATE_TIME",
    "PHONE": "PHONE_NUMBER",
    "ID": "ID",
}

# Entities the job redacts. Includes Presidio's built-in pattern/checksum
# recognizers, which fire independently of the NER model.
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
    # NOTE: no "LOCATION". The transformers NLP engine means spaCy's own
    # NER never runs, and the Stanford model has no location label, so
    # nothing would satisfy it -- Presidio just warns at startup.
    # Geography is covered by STREET_ADDRESS / US_ZIP_CODE below.
    # Added by deid/recognizers.py to cover the NER model's gaps.
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
    # Recorded for the report only. PaddleOCR ignores a `lang` argument
    # when explicit model names are set, and PP-OCRv6 medium/small are
    # single multilingual models (50 languages) -- language is chosen by
    # picking the model, not by this value.
    ocr_lang: str = field(default_factory=lambda: os.environ.get("OCR_LANG", "en"))
    # "cpu" or "gpu:0". Cloudera AI job nodes here are CPU.
    device: str = field(
        default_factory=lambda: os.environ.get("OCR_DEVICE", "cpu")
    )
    # Rasterisation DPI. 200 is the accuracy/runtime sweet spot for OCR;
    # below ~150 recognition degrades badly on small print.
    dpi: int = field(default_factory=lambda: _env_int("OCR_DPI", 200))
    # Skip OCR results below this confidence -- they are usually noise
    # and can create spurious redaction boxes.
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
    # oneDNN is off because it crashes the PP-OCRv6 detector on
    # paddlepaddle 3.3.1 (see ocr_engine.py). It is normally a CPU
    # speedup, so re-test and re-enable on a newer paddlepaddle.
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
    # Presidio score threshold. Deliberately low: for de-identification a
    # false positive (over-redaction) is far cheaper than a false
    # negative (leaked PHI).
    score_threshold: float = field(
        default_factory=lambda: _env_float("DEID_SCORE_THRESHOLD", 0.35)
    )
    entities: List[str] = field(default_factory=lambda: list(DEFAULT_ENTITIES))

    # --- Redaction ---
    # Pixels to grow each redaction box, so glyph edges/descenders that
    # sit outside the OCR polygon still get covered.
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
    # Include the detected PII values in the report. Off by default --
    # a report full of the PII you just redacted is itself a PHI leak.
    report_include_values: bool = field(
        default_factory=lambda: _env_bool("DEID_REPORT_INCLUDE_VALUES", False)
    )

    def __post_init__(self):
        env_entities = os.environ.get("DEID_ENTITIES")
        if env_entities:
            self.entities = [e.strip() for e in env_entities.split(",") if e.strip()]


def load_config() -> Config:
    return Config()
