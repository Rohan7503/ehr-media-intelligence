"""Deterministic FHIR resource identifiers.

Resource IDs are UUIDv5 values derived from the resource type and the
canonical identifiers of the thing being mapped. The same canonical input
always yields the same UUID, so Bundle content — including internal
references and entry ``fullUrl`` values — is stable across runs. Random
(UUIDv4) identifiers are never used.

A UUID string (36 lowercase hex-and-hyphen characters) satisfies the FHIR
``id`` restriction ``[A-Za-z0-9-.]{1,64}``.
"""

from uuid import uuid5

from app.domain.record import ClinicalRecord
from app.fhir.constants import NAMESPACE_UUID


def _resource_uuid(
    resource_type: str,
    patient_id: str,
    *,
    encounter_id: str | None = None,
    record_id: str | None = None,
) -> str:
    """Derive a stable UUIDv5 string from canonical identifiers."""
    name = "|".join([resource_type, patient_id, encounter_id or "", record_id or ""])
    return str(uuid5(NAMESPACE_UUID, name))


def patient_resource_id(patient_id: str) -> str:
    return _resource_uuid("Patient", patient_id)


def encounter_resource_id(patient_id: str, encounter_id: str) -> str:
    return _resource_uuid("Encounter", patient_id, encounter_id=encounter_id)


def record_resource_id(record: ClinicalRecord) -> str:
    """Resource ID for a clinical record's mapped resource.

    The resource type name distinguishes document from diagnostic mappings so
    the two never collide, even for otherwise-identical identifiers.
    """
    resource_type = (
        "DocumentReference" if record.record_type.value == "document" else "DiagnosticReport"
    )
    return _resource_uuid(resource_type, record.patient_id, record_id=record.record_id)


def full_url(resource_id: str) -> str:
    """Bundle-entry ``fullUrl`` for a resource ID (``urn:uuid:`` form)."""
    return f"urn:uuid:{resource_id}"
