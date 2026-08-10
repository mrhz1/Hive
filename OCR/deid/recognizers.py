"""Extra pattern recognizers."""
from typing import List

from presidio_analyzer import Pattern, PatternRecognizer


def _us_zip_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="US_ZIP_CODE",
        name="UsZipCodeRecognizer",
        patterns=[
            Pattern(name="us_zip_plus4", regex=r"\b\d{5}-\d{4}\b", score=0.6),
            Pattern(name="us_zip", regex=r"\b\d{5}\b", score=0.3),
        ],
        context=["zip", "zipcode", "postal", "address", "city", "state"],
    )


def _street_address_recognizer() -> PatternRecognizer:
    street_types = (
        r"(?:St(?:reet)?|Ave(?:nue)?|Blvd|Boulevard|Rd|Road|Ln|Lane|Dr(?:ive)?|"
        r"Ct|Court|Cir(?:cle)?|Pl(?:ace)?|Way|Ter(?:race)?|Pkwy|Parkway|Hwy|Highway)"
    )
    return PatternRecognizer(
        supported_entity="STREET_ADDRESS",
        name="StreetAddressRecognizer",
        patterns=[
            Pattern(
                name="street_address",
                regex=rf"\b\d{{1,6}}\s+(?:[A-Z][A-Za-z.'-]*\s+){{0,4}}{street_types}\b\.?",
                score=0.6,
            ),
            Pattern(
                name="po_box",
                regex=r"\b[Pp]\.?\s?[Oo]\.?\s?Box\s+\d+\b",
                score=0.7,
            ),
            Pattern(
                name="apt_suite",
                regex=r"\b(?:Apt|Apartment|Suite|Ste|Unit|Rm|Room)\.?\s*#?\s*[\w-]+\b",
                score=0.4,
            ),
        ],
        context=["address", "street", "residence", "home", "lives", "mailing"],
    )


def _mrn_recognizer() -> PatternRecognizer:
    """Medical record numbers."""
    return PatternRecognizer(
        supported_entity="MRN",
        name="MedicalRecordNumberRecognizer",
        patterns=[
            Pattern(
                name="mrn_labelled",
                regex=r"\b(?:MRN|Medical\s+Record(?:\s+(?:No|Number|#))?|"
                r"Patient\s+(?:ID|No|Number|#)|Chart\s*#?)\s*[:#]?\s*([A-Z0-9-]{4,15})\b",
                score=0.75,
            ),
            Pattern(name="mrn_bare", regex=r"\b[A-Z]{2,3}\d{6,10}\b", score=0.35),
        ],
        context=["mrn", "medical", "record", "patient", "chart", "admission"],
    )


def _age_recognizer() -> PatternRecognizer:
    """HIPAA Safe Harbor: ages over 89 are identifiers and must go."""
    return PatternRecognizer(
        supported_entity="AGE",
        name="ElderlyAgeRecognizer",
        patterns=[
            Pattern(
                name="age_over_89",
                regex=r"\b(?:9\d|1\d{2})\s*(?:-|\s)?\s*(?:years?[- ]old|y/?o|yrs?)\b",
                score=0.7,
            ),
            Pattern(
                name="age_label_over_89",
                regex=r"\bAge\s*[:=]?\s*(?:9\d|1\d{2})\b",
                score=0.7,
            ),
        ],
        context=["age", "years", "old", "dob", "birth"],
    )


def build_custom_recognizers() -> List[PatternRecognizer]:
    return [
        _us_zip_recognizer(),
        _street_address_recognizer(),
        _mrn_recognizer(),
        _age_recognizer(),
    ]
