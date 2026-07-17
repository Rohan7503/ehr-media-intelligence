"""GET /patients/{patient_id} — patient detail for the clinician interface.

Assembles the view from the stored valid FHIR Bundle and the matching cached
summary. Clinical text is decoded to readable strings (never raw base64), the
summarization provider is never invoked, and unknown patients return 404.
"""

import json
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.persistence.database import create_db_engine, init_db
from app.persistence.repositories.bundles import BundleRepository
from app.summarization.cache import SummaryRepository
from app.summarization.evidence import extract_patient_evidence
from app.summarization.summary import ClinicalSummary

router = APIRouter()


class LinkedResource(BaseModel):
    """One clinical resource linked to the patient, as readable text."""

    resource_id: str
    resource_type: str
    record_date: str | None = None
    title: str
    text: str


class PatientDetailResponse(BaseModel):
    """Typed patient-detail response."""

    patient_id: str
    patient_name: str
    mrn: str
    date_of_birth: str | None = None
    gender: str | None = None
    bundle_valid: bool
    summary: ClinicalSummary | None = None
    summary_confidence: str | None = None
    summary_disclaimer: str | None = None
    resources: list[LinkedResource]


@lru_cache
def _get_engine() -> Engine:
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    init_db(engine)
    return engine


def get_session() -> Iterator[Session]:
    """Provide a request-scoped Session (overridden in tests)."""
    engine = _get_engine()
    with Session(engine) as session:
        yield session


def _patient_demographics(bundle: dict[str, object]) -> tuple[str, str, str | None, str | None]:
    """Extract ``(name, mrn, birth_date, gender)`` from the Patient resource."""
    entries = bundle.get("entry")
    if not isinstance(entries, list):
        return "", "", None, None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        resource = entry.get("resource")
        if not isinstance(resource, dict) or resource.get("resourceType") != "Patient":
            continue
        name = ""
        names = resource.get("name")
        if isinstance(names, list) and names and isinstance(names[0], dict):
            parts: list[str] = []
            given = names[0].get("given")
            if isinstance(given, list):
                parts.extend(str(token) for token in given)
            family = names[0].get("family")
            if isinstance(family, str):
                parts.append(family)
            name = " ".join(parts)
        mrn = ""
        identifiers = resource.get("identifier")
        if isinstance(identifiers, list) and identifiers and isinstance(identifiers[0], dict):
            value = identifiers[0].get("value")
            if isinstance(value, str):
                mrn = value
        birth_date = resource.get("birthDate")
        gender = resource.get("gender")
        return (
            name,
            mrn,
            birth_date if isinstance(birth_date, str) else None,
            gender if isinstance(gender, str) else None,
        )
    return "", "", None, None


@router.get("/patients/{patient_id}", response_model=PatientDetailResponse)
def get_patient(
    patient_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> PatientDetailResponse:
    """Return the detail view for a patient with a stored valid Bundle."""
    bundle = BundleRepository(session).get_bundle_by_patient_id(patient_id)
    if bundle is None or not bundle.valid:
        raise HTTPException(status_code=404, detail="patient not found")

    demographics = _patient_demographics(json.loads(bundle.bundle_json))
    name, mrn, birth_date, gender = demographics

    evidence = extract_patient_evidence(patient_id, bundle.bundle_json)
    resources = [
        LinkedResource(
            resource_id=record.resource_id,
            resource_type=record.resource_type,
            record_date=record.date,
            title=record.title or record.resource_type,
            text=record.text,
        )
        for record in evidence.records
    ]

    summary = _load_summary(session, patient_id, bundle.bundle_hash)
    return PatientDetailResponse(
        patient_id=patient_id,
        patient_name=name,
        mrn=mrn,
        date_of_birth=birth_date,
        gender=gender,
        bundle_valid=bundle.valid,
        summary=summary,
        summary_confidence=summary.confidence.value if summary else None,
        summary_disclaimer=summary.disclaimer if summary else None,
        resources=resources,
    )


def _load_summary(session: Session, patient_id: str, bundle_hash: str) -> ClinicalSummary | None:
    rows = SummaryRepository(session).list_for_bundle(patient_id, bundle_hash)
    if not rows:
        return None
    return ClinicalSummary.model_validate_json(rows[0].summary_json)
