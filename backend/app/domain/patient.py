"""Canonical patient model."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.audit import AuditEntry


class Gender(StrEnum):
    """Canonical administrative gender.

    Values align with the FHIR R4 administrative-gender code set so later
    FHIR mapping is direct. Source variants such as ``X``, ``nonbinary``, and
    ``NB`` normalize to ``OTHER``; missing or unrecognized values normalize
    to ``UNKNOWN``. Gender is never inferred from names or other fields.
    """

    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNKNOWN = "unknown"


class Patient(BaseModel):
    """A canonical patient assembled from one or more source records.

    Identity is keyed on the normalized MRN; ``patient_id`` is derived
    deterministically from it. Optional demographics stay ``None`` when the
    sources never provide them — values are never invented.
    """

    patient_id: str
    source_patient_ids: list[str] = Field(default_factory=list)
    mrn: str
    given_name: str | None = None
    family_name: str | None = None
    birth_date: date | None = None
    gender: Gender = Gender.UNKNOWN
    audit: list[AuditEntry] = Field(default_factory=list)
