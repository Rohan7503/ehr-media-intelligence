"""Shared loader types and the canonical field-alias mapping.

Loaders parse a source file into :class:`RawRecord` objects whose ``fields``
use one canonical vocabulary regardless of source format. All alternate
column and key names are handled here through one explicit alias table.
"""

from pydantic import BaseModel, Field

from app.domain.record import SourceFormat

#: Canonical raw-field names produced by every loader.
CANONICAL_FIELDS = frozenset(
    {
        "patient_id",
        "mrn",
        "given_name",
        "family_name",
        "full_name",
        "dob",
        "gender",
        "record_id",
        "encounter_id",
        "record_type",
        "record_date",
        "title",
        "text",
        "diagnostic_code",
    }
)

#: Alternate source names (normalized to lowercase snake_case) → canonical name.
FIELD_ALIASES: dict[str, str] = {
    "patient_id": "patient_id",
    "patientid": "patient_id",
    "source_patient_id": "patient_id",
    "pid": "patient_id",
    "mrn": "mrn",
    "medical_record_number": "mrn",
    "mrn_number": "mrn",
    "given_name": "given_name",
    "first_name": "given_name",
    "fname": "given_name",
    "family_name": "family_name",
    "last_name": "family_name",
    "surname": "family_name",
    "lname": "family_name",
    "name": "full_name",
    "full_name": "full_name",
    "patient_name": "full_name",
    "dob": "dob",
    "date_of_birth": "dob",
    "birth_date": "dob",
    "birthdate": "dob",
    "gender": "gender",
    "sex": "gender",
    "record_id": "record_id",
    "note_id": "record_id",
    "document_id": "record_id",
    "encounter_id": "encounter_id",
    "visit_id": "encounter_id",
    "record_type": "record_type",
    "type": "record_type",
    "note_type": "record_type",
    "record_date": "record_date",
    "date": "record_date",
    "service_date": "record_date",
    "date_of_service": "record_date",
    "title": "title",
    "subject": "title",
    "text": "text",
    "note_text": "text",
    "note": "text",
    "body": "text",
    "content": "text",
    "diagnostic_code": "diagnostic_code",
    "code": "diagnostic_code",
    "icd_code": "diagnostic_code",
}


def canonical_key(raw_key: str) -> str | None:
    """Map a source column or key name to its canonical field name.

    Unrecognized names return ``None`` and are ignored by loaders.
    """
    normalized = raw_key.strip().lower().replace("-", "_").replace(" ", "_")
    return FIELD_ALIASES.get(normalized)


class RawRecord(BaseModel):
    """One source record as extracted by a loader, before normalization.

    ``issues`` carries loader-detected structural problems; the pipeline
    rejects records that have any.
    """

    source_file: str
    source_format: SourceFormat
    index: int
    fields: dict[str, str] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
