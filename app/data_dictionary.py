from typing import Dict, List, Tuple

Definition = Tuple[str, str, str]

SHIFTED = (
    "Moved by the patient's own number of days (the same for all their "
    "dates, up to 5 years either way), so intervals are true; calendar dates are not"
)

RELEASE: Dict[str, Dict[str, Definition]] = {
    "patients.csv": {
        "project_patient_id": (
            "text", "The patient's ID in this project only",
            "<project code>-<6 letters/digits>; cannot be matched to Zone 1 codes",
        ),
        "age_at_registration": (
            "integer or text", "Age in whole years on the registration date",
            "90+ for 90 and over; empty if a date is missing",
        ),
        "registration_date": ("date YYYY-MM-DD", "Date the patient was registered", SHIFTED),
        "death_date": ("date YYYY-MM-DD", "Date of death; empty if alive or unknown", SHIFTED),
        "state": ("text", "State or province of the patient's address", ""),
        "country": ("text", "Country of the patient's address", ""),
    },
    "applications.csv": {
        "project_application_id": (
            "text", "The submission's ID in this project only", "<project code>-A<6 letters/digits>",
        ),
        "project_patient_id": ("text", "The patient it belongs to", "See patients.csv"),
        "status": ("text", "Status of the submission", "submitted, approved"),
        "created_date": ("date YYYY-MM-DD", "Date the submission was started", SHIFTED),
        "submitted_date": ("date YYYY-MM-DD", "Date it was submitted", SHIFTED),
    },
    "documents.csv": {
        "project_document_id": (
            "text", "The document's ID in this project only", "<project code>-D<6 letters/digits>",
        ),
        "project_application_id": ("text", "The submission it came with", "See applications.csv"),
        "project_patient_id": ("text", "The patient it belongs to", "See patients.csv"),
        "file_type": ("text", "File format", "pdf, dcm, docx, ..."),
        "modality": ("text", "Type of document or imaging modality", "e.g. ECHO, MR, DISCHARGE; UNKNOWN if it could not be read"),
        "document_date": ("date YYYY-MM-DD", "Date of the document itself", SHIFTED),
        "file_size_bytes": ("integer", "Size of the original file in bytes", ""),
        "created_date": ("date YYYY-MM-DD", "Date the document was added", SHIFTED),
        "file": (
            "text", "Path of the de-identified file in this folder",
            "Empty when the project is not approved for documents",
        ),
    },
}

FILE_METADATA_EXPORT: Dict[str, str] = {
    "File": "Name of the document as it was received",
    "File id": "The document's ID in Hive",
    "Patient id": "Patient code",
    "Application id": "The submission the document is attached to",
    "Type": "File format the metadata was read from (pdf, dicom, docx, doc)",
    "Status": "ok: read; unsupported: no metadata for this format; failed: could not be read",
    "Error": "Why reading failed, if it did",
    "Extracted at": "When the metadata was read (UTC)",
}

METADATA_FIELDS = (
    "Other columns",
    "Fields stored inside the files (PDF properties, DICOM tags, Word "
    "properties), as found; a column is empty when a file doesn't have it",
)


def release_rows() -> List[List[str]]:
    rows = []
    for file, columns in RELEASE.items():
        for column, (kind, meaning, values) in columns.items():
            rows.append([file, column, kind, meaning, values])
    return rows


RELEASE_HEADER = ["file", "column", "type", "meaning", "values / notes"]


def file_metadata_export() -> List[Tuple[str, str]]:
    return [*FILE_METADATA_EXPORT.items(), METADATA_FIELDS]


METADATA_EXPORT = [
    ("Field", "Name of a field stored inside the file (PDF property, DICOM tag, Word property)"),
    ("Value", "Its value as found in the file"),
]
