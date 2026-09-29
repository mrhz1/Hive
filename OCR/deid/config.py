import os
from typing import Dict, List


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


DEFAULT_DET_MODEL = "PP-OCRv6_medium_det"
DEFAULT_REC_MODEL = "PP-OCRv6_medium_rec"

DEFAULT_SPACY_MODEL = "en_core_web_sm"
DEFAULT_TRANSFORMERS_MODEL = "StanfordAIMI/stanford-deidentifier-base"

MODEL_TO_PRESIDIO_ENTITY: Dict[str, str] = {
    "PATIENT": "PERSON",
    "HCW": "PERSON",
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


class Config:
    def __init__(self):
        self.det_model = os.environ.get("OCR_DET_MODEL", DEFAULT_DET_MODEL)
        self.rec_model = os.environ.get("OCR_REC_MODEL", DEFAULT_REC_MODEL)
        self.ocr_lang = os.environ.get("OCR_LANG", "en")
        self.device = os.environ.get("OCR_DEVICE", "cpu")
        self.dpi = _env_int("OCR_DPI", 200)
        self.min_ocr_confidence = _env_float("OCR_MIN_CONFIDENCE", 0.5)
        self.use_doc_orientation_classify = _env_bool("OCR_DOC_ORIENTATION", False)
        self.use_doc_unwarping = _env_bool("OCR_DOC_UNWARPING", False)
        self.use_textline_orientation = _env_bool("OCR_TEXTLINE_ORIENTATION", False)
        self.enable_mkldnn = _env_bool("OCR_ENABLE_MKLDNN", False)
        self.cpu_threads = _env_int("OCR_CPU_THREADS", 8)

        self.spacy_model = os.environ.get("DEID_SPACY_MODEL", DEFAULT_SPACY_MODEL)
        self.transformers_model = os.environ.get(
            "DEID_TRANSFORMERS_MODEL", DEFAULT_TRANSFORMERS_MODEL
        )
        self.score_threshold = _env_float("DEID_SCORE_THRESHOLD", 0.35)

        self.entities = list(DEFAULT_ENTITIES)
        env_entities = os.environ.get("DEID_ENTITIES")
        if env_entities:
            self.entities = [e.strip() for e in env_entities.split(",") if e.strip()]

        self.box_padding = _env_float("DEID_BOX_PADDING", 2.0)
        self.redaction_fill = os.environ.get("DEID_REDACTION_FILL", "black")
        self.write_text = _env_bool("DEID_WRITE_TEXT", True)
        self.write_report = _env_bool("DEID_WRITE_REPORT", True)
        self.report_include_values = _env_bool("DEID_REPORT_INCLUDE_VALUES", False)


def load_config() -> Config:
    return Config()
