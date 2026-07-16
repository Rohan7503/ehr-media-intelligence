"""Map canonical domain models to FHIR R4-compatible resources.

The mapper reads canonical :class:`Patient` and :class:`ClinicalRecord`
models (never mutating them) and produces ``fhir.resources.R4B`` resources
restricted to fields shared with FHIR R4 4.0.1. Clinical text is preserved
verbatim in a self-contained base64 ``Attachment``; no medical terminology
codes are invented.

Determinism: all identifiers are UUIDv5-derived and no timestamps enter the
output, so mapping the same canonical input yields byte-identical Bundles.
"""

import base64
from datetime import date, datetime

from fhir.resources.R4B.attachment import Attachment
from fhir.resources.R4B.bundle import Bundle, BundleEntry
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.documentreference import (
    DocumentReference,
    DocumentReferenceContent,
    DocumentReferenceContext,
)
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.humanname import HumanName
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.patient import Patient as FHIRPatient
from fhir.resources.R4B.period import Period
from pydantic import BaseModel

from app.domain.patient import Patient
from app.domain.record import ClinicalRecord, RecordType
from app.fhir import constants
from app.fhir.identifiers import (
    encounter_resource_id,
    full_url,
    patient_resource_id,
    record_resource_id,
)
from app.fhir.references import reference_to


class MappedBundle(BaseModel):
    """A generated Bundle plus the metadata the pipeline needs downstream."""

    model_config = {"arbitrary_types_allowed": True}

    patient_id: str
    bundle_id: str
    bundle: Bundle
    #: Canonical record IDs expected to appear exactly once as clinical
    #: resources in this Bundle (drives reference-integrity coverage checks).
    expected_record_ids: list[str]
    #: Map of clinical resource ID -> canonical record type value.
    clinical_resource_types: dict[str, str]


def _date_str(value: date | datetime | None) -> str | None:
    """Render a canonical record date as a FHIR date/dateTime string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def map_patient(patient: Patient) -> FHIRPatient:
    """Map a canonical patient to a FHIR Patient resource."""
    identifier = Identifier(
        use="official",
        type=CodeableConcept(
            coding=[
                Coding(
                    system=constants.IDENTIFIER_TYPE_SYSTEM,
                    code=constants.MRN_TYPE_CODE,
                    display=constants.MRN_TYPE_DISPLAY,
                )
            ]
        ),
        system=constants.MRN_SYSTEM,
        value=patient.mrn,
    )
    names = None
    if patient.family_name is not None or patient.given_name is not None:
        names = [
            HumanName(
                family=patient.family_name,
                given=[patient.given_name] if patient.given_name else None,
            )
        ]
    return FHIRPatient(
        id=patient_resource_id(patient.patient_id),
        identifier=[identifier],
        name=names,
        gender=patient.gender.value,
        birthDate=_date_str(patient.birth_date),
    )


def map_encounter(patient: Patient, encounter_id: str, records: list[ClinicalRecord]) -> Encounter:
    """Map a unique canonical encounter ID to a FHIR Encounter resource.

    The period is derived from the associated records' dates: start is the
    earliest known date and end the latest. When no associated record has a
    date, the period is omitted rather than invented.
    """
    dates = sorted(
        record.record_date.date()
        if isinstance(record.record_date, datetime)
        else record.record_date
        for record in records
        if record.record_date is not None
    )
    period = None
    if dates:
        period = Period(start=dates[0].isoformat(), end=dates[-1].isoformat())
    return Encounter(
        id=encounter_resource_id(patient.patient_id, encounter_id),
        status=constants.ENCOUNTER_STATUS,
        class_fhir=Coding(
            system=constants.ENCOUNTER_CLASS_SYSTEM,
            code=constants.ENCOUNTER_CLASS_CODE,
            display=constants.ENCOUNTER_CLASS_DISPLAY,
        ),
        subject=reference_to(patient_resource_id(patient.patient_id)),
        period=period,
    )


def _attachment(record: ClinicalRecord) -> Attachment:
    """A self-contained text/plain attachment holding the clinical text."""
    encoded = base64.b64encode(record.text.encode("utf-8")).decode("ascii")
    return Attachment(
        contentType=constants.ATTACHMENT_CONTENT_TYPE,
        data=encoded,
        title=record.title,
    )


def map_document_reference(
    patient: Patient, record: ClinicalRecord, *, encounter_id: str | None
) -> DocumentReference:
    """Map a canonical ``document`` record to a DocumentReference resource."""
    context = None
    context_encounter = (
        [reference_to(encounter_resource_id(patient.patient_id, encounter_id))]
        if encounter_id
        else None
    )
    date_str = _date_str(record.record_date)
    context_period = Period(start=date_str) if date_str else None
    if context_encounter is not None or context_period is not None:
        context = DocumentReferenceContext(encounter=context_encounter, period=context_period)
    return DocumentReference(
        id=record_resource_id(record),
        status=constants.DOCUMENT_REFERENCE_STATUS,
        subject=reference_to(patient_resource_id(patient.patient_id)),
        type=CodeableConcept(text=record.title),
        content=[DocumentReferenceContent(attachment=_attachment(record))],
        context=context,
    )


def map_diagnostic_report(
    patient: Patient, record: ClinicalRecord, *, encounter_id: str | None
) -> DiagnosticReport:
    """Map a canonical ``diagnostic_report`` record to a DiagnosticReport.

    The source diagnostic code, when present, is preserved as an Identifier in
    a clearly project-owned namespace — it is never asserted to belong to an
    external terminology such as LOINC, SNOMED CT, or ICD.
    """
    identifiers = None
    if record.diagnostic_code is not None:
        identifiers = [
            Identifier(
                system=constants.SOURCE_DIAGNOSTIC_CODE_SYSTEM,
                value=record.diagnostic_code,
            )
        ]
    encounter_ref = (
        reference_to(encounter_resource_id(patient.patient_id, encounter_id))
        if encounter_id
        else None
    )
    return DiagnosticReport(
        id=record_resource_id(record),
        identifier=identifiers,
        status=constants.DIAGNOSTIC_REPORT_STATUS,
        code=CodeableConcept(text=record.title),
        subject=reference_to(patient_resource_id(patient.patient_id)),
        encounter=encounter_ref,
        effectiveDateTime=_date_str(record.record_date),
        conclusion=record.text,
        presentedForm=[_attachment(record)],
    )


def _clinical_sort_key(record: ClinicalRecord) -> tuple[int, str, str, str]:
    """Deterministic order: dated records first (chronologically), then type, id.

    Undated records are still included and sorted deterministically after
    dated ones.
    """
    dated = record.record_date is not None
    date_str = record.record_date.isoformat() if record.record_date else ""
    return (0 if dated else 1, date_str, record.record_type.value, record.record_id)


def map_patient_bundle(patient: Patient, records: list[ClinicalRecord]) -> MappedBundle:
    """Map one canonical patient and its accepted records to a Bundle.

    Entry order is deterministic: the Patient first, then Encounters in
    resource-ID order, then clinical resources in (date, type, id) order.
    """
    patient_res = map_patient(patient)
    patient_res_id = patient_res.id
    assert patient_res_id is not None
    entries: list[BundleEntry] = [
        BundleEntry(fullUrl=full_url(patient_res_id), resource=patient_res)
    ]

    encounter_ids = sorted(
        {record.encounter_id for record in records if record.encounter_id is not None}
    )
    encounters: list[Encounter] = []
    for encounter_id in encounter_ids:
        encounter_records = [r for r in records if r.encounter_id == encounter_id]
        encounters.append(map_encounter(patient, encounter_id, encounter_records))
    for encounter in sorted(encounters, key=lambda enc: enc.id or ""):
        assert encounter.id is not None
        entries.append(BundleEntry(fullUrl=full_url(encounter.id), resource=encounter))

    expected_record_ids: list[str] = []
    clinical_resource_types: dict[str, str] = {}
    for record in sorted(records, key=_clinical_sort_key):
        resource: DocumentReference | DiagnosticReport
        if record.record_type is RecordType.DOCUMENT:
            resource = map_document_reference(patient, record, encounter_id=record.encounter_id)
        else:
            resource = map_diagnostic_report(patient, record, encounter_id=record.encounter_id)
        resource_id = resource.id
        assert resource_id is not None
        entries.append(BundleEntry(fullUrl=full_url(resource_id), resource=resource))
        expected_record_ids.append(record.record_id)
        clinical_resource_types[resource_id] = record.record_type.value

    bundle_id = patient_res_id
    bundle = Bundle(id=bundle_id, type=constants.BUNDLE_TYPE, entry=entries)
    return MappedBundle(
        patient_id=patient.patient_id,
        bundle_id=bundle_id,
        bundle=bundle,
        expected_record_ids=expected_record_ids,
        clinical_resource_types=clinical_resource_types,
    )
