from typing import Dict, List, Set

from app import consent, document_info, zone2
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
from app.crud import patients as patients_crud
from app.project_schemas import CohortCriteria, CohortSearchResult, Project


def _upper(values: List[str]) -> Set[str]:
    return {v.strip().upper() for v in values if v and v.strip()}


def _age(patient) -> int:
    birth, on = patient.dt_b, patient.dt_reg
    if not birth or not on:
        return -1
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def _documents_by_patient(cursor) -> Dict[str, List[tuple]]:
    owner = {
        a.id: a.patient_id
        for a in applications_crud.list_applications(cursor)
        if a.status in zone2.RELEASED_STATUSES
    }
    out: Dict[str, List[tuple]] = {}
    for record in files_crud.list_files(cursor):
        code = owner.get(record.application_id)
        if not code or record.review_status == "deleted" or record.deid_status != "done":
            continue
        out.setdefault(code, []).append(
            (record.modality or document_info.UNKNOWN, record.document_date or "")
        )
    return out


def _document_matches(docs: List[tuple], criteria: CohortCriteria) -> bool:
    modalities = {document_info.clean_modality(m) or m.upper() for m in criteria.modalities if m.strip()}
    low = criteria.document_from.strftime("%Y%m%d") if criteria.document_from else None
    high = criteria.document_to.strftime("%Y%m%d") if criteria.document_to else None
    for modality, day in docs:
        if modalities and modality not in modalities:
            continue
        if low or high:
            if not day.isdigit():
                continue
            if (low and day < low) or (high and day > high):
                continue
        return True
    return False


def search(cursor, project: Project, criteria: CohortCriteria) -> CohortSearchResult:
    codes = [c.patient_id for c in zone2.candidates(cursor)]
    patients = {p.id: p for p in patients_crud.list_patients(cursor)}
    prefixes = _upper(criteria.prefixes)
    countries, states = _upper(criteria.countries), _upper(criteria.states)
    institutions, skip = _upper(criteria.institution_codes), _upper(criteria.exclude_codes)
    wants_documents = bool(
        [m for m in criteria.modalities if m.strip()] or criteria.document_from or criteria.document_to
    )
    documents = _documents_by_patient(cursor) if wants_documents else {}

    matched = []
    for code in codes:
        patient = patients.get(code)
        if patient is None or code in skip:
            continue
        if prefixes and not any(code.startswith(p) for p in prefixes):
            continue
        registered = patient.dt_reg
        if criteria.registered_from and (not registered or registered < criteria.registered_from):
            continue
        if criteria.registered_to and (not registered or registered > criteria.registered_to):
            continue
        if criteria.age_min is not None or criteria.age_max is not None:
            age = _age(patient)
            if age < 0:
                continue
            if criteria.age_min is not None and age < criteria.age_min:
                continue
            if criteria.age_max is not None and age > criteria.age_max:
                continue
        if countries and (patient.ptcountry or "").strip().upper() not in countries:
            continue
        if states and (patient.ptstate or "").strip().upper() not in states:
            continue
        if institutions and (patient.instcode or "").strip().upper() not in institutions:
            continue
        if criteria.alive_only and patient.dt_d:
            continue
        if wants_documents and not _document_matches(documents.get(code, []), criteria):
            continue
        matched.append(code)

    excluded = consent.excluded(cursor, project, matched)
    return CohortSearchResult(
        matches=[c for c in matched if c not in excluded], excluded=excluded
    )
