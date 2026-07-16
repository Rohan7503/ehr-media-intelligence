"""Validation layers for generated Bundles.

Three independent layers run over each Bundle:

1. ``fhir.resources`` model validation — re-parses the serialized Bundle
   through the library models, catching any structural/typing violation as a
   structured issue instead of a raw exception.
2. Reference integrity — a project validator, independent of Pydantic, that
   checks Bundle-level invariants (single Patient, unique IDs and fullUrls,
   resolvable local references, complete and exclusive record coverage,
   matching resource types, valid attachment payloads, deterministic order).
3. R4 compatibility guard — ``app.fhir.compatibility`` confirms only
   allowlisted R4 fields and resource types are emitted.

Broken references are reported, never silently repaired.
"""

import base64
import binascii

from fhir.resources.R4B.bundle import Bundle
from pydantic import ValidationError

from app.fhir.compatibility import check_bundle_compatibility
from app.fhir.mapper import MappedBundle
from app.fhir.report import PatientBundleValidation, ValidationIssue

_CLINICAL_TYPE_FOR_RECORD = {
    "document": "DocumentReference",
    "diagnostic_report": "DiagnosticReport",
}


def validate_bundle(mapped: MappedBundle) -> PatientBundleValidation:
    """Run all validation layers and produce a per-patient validation result."""
    bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
    issues: list[ValidationIssue] = []
    issues.extend(_validate_with_library(bundle_json))
    issues.extend(_validate_reference_integrity(bundle_json, mapped))
    issues.extend(check_bundle_compatibility(bundle_json))

    valid = not any(issue.severity == "error" for issue in issues)
    return PatientBundleValidation(
        patient_id=mapped.patient_id,
        bundle_id=mapped.bundle_id,
        valid=valid,
        resource_counts=count_resources(bundle_json),
        issues=issues,
    )


def count_resources(bundle_json: dict[str, object]) -> dict[str, int]:
    """Count resources in a Bundle by ``resourceType``."""
    counts: dict[str, int] = {}
    for resource in _resources(bundle_json):
        resource_type = resource.get("resourceType")
        if isinstance(resource_type, str):
            counts[resource_type] = counts.get(resource_type, 0) + 1
    return counts


def _validate_with_library(bundle_json: dict[str, object]) -> list[ValidationIssue]:
    try:
        Bundle.model_validate(bundle_json)
    except ValidationError as exc:
        return [
            ValidationIssue(
                severity="error",
                code="fhir-model-validation",
                message=f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}",
                validator="fhir.resources",
                location=".".join(str(p) for p in error["loc"]),
            )
            for error in exc.errors()
        ]
    return []


def _resources(bundle_json: dict[str, object]) -> list[dict[str, object]]:
    entries = bundle_json.get("entry")
    if not isinstance(entries, list):
        return []
    resources: list[dict[str, object]] = []
    for entry in entries:
        if isinstance(entry, dict):
            resource = entry.get("resource")
            if isinstance(resource, dict):
                resources.append(resource)
    return resources


def _validate_reference_integrity(
    bundle_json: dict[str, object], mapped: MappedBundle
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    entries = bundle_json.get("entry")
    if not isinstance(entries, list):
        return [
            ValidationIssue(
                severity="error",
                code="missing-entries",
                message="Bundle has no entry array",
                validator="reference_integrity",
            )
        ]

    def error(code: str, message: str, **kw: str | None) -> None:
        issues.append(
            ValidationIssue(
                severity="error", code=code, message=message, validator="reference_integrity", **kw
            )
        )

    full_urls: list[str] = []
    resource_ids: list[str] = []
    patient_full_urls: list[str] = []
    encounter_full_urls: set[str] = set()
    clinical: list[tuple[str, dict[str, object]]] = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            error("invalid-entry", f"entry[{index}] is not an object")
            continue
        full_url = entry.get("fullUrl")
        if isinstance(full_url, str):
            full_urls.append(full_url)
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            error("missing-resource", f"entry[{index}] has no resource")
            continue
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        if not isinstance(resource_id, str) or not resource_id:
            error(
                "missing-resource-id",
                f"entry[{index}] resource has no id",
                resource_type=resource_type if isinstance(resource_type, str) else None,
            )
            continue
        resource_ids.append(resource_id)
        entry_url = f"urn:uuid:{resource_id}"
        if full_url != entry_url:
            error(
                "fullurl-mismatch",
                f"entry[{index}] fullUrl {full_url!r} does not match resource id {resource_id!r}",
                resource_id=resource_id,
            )
        if resource_type == "Patient":
            patient_full_urls.append(entry_url)
        elif resource_type == "Encounter":
            encounter_full_urls.add(entry_url)
        elif resource_type in ("DocumentReference", "DiagnosticReport"):
            clinical.append((resource_id, resource))

    # 1. exactly one Patient
    if len(patient_full_urls) != 1:
        error(
            "patient-cardinality",
            f"Bundle must have exactly one Patient, found {len(patient_full_urls)}",
        )
    patient_url = patient_full_urls[0] if patient_full_urls else None

    # 3 & 4. uniqueness
    for value in _duplicates(resource_ids):
        error("duplicate-resource-id", f"duplicate resource id: {value}")
    for value in _duplicates(full_urls):
        error("duplicate-fullurl", f"duplicate fullUrl: {value}")

    # 5-8. subject/encounter references resolve to this Bundle's Patient/Encounters
    for resource in _resources(bundle_json):
        resource_id = resource.get("id")
        rid = resource_id if isinstance(resource_id, str) else None
        subject_ref = _ref(resource.get("subject"))
        if subject_ref is not None and subject_ref != patient_url:
            error(
                "unresolved-subject",
                f"subject reference {subject_ref!r} does not resolve to the Bundle Patient",
                resource_type=_str(resource.get("resourceType")),
                resource_id=rid,
            )
        encounter_ref = _ref(resource.get("encounter"))
        if encounter_ref is not None and encounter_ref not in encounter_full_urls:
            error(
                "unresolved-encounter",
                f"encounter reference {encounter_ref!r} does not resolve to a Bundle Encounter",
                resource_type=_str(resource.get("resourceType")),
                resource_id=rid,
            )
        for ctx_ref in _context_encounter_refs(resource):
            if ctx_ref not in encounter_full_urls:
                error(
                    "unresolved-encounter",
                    f"context encounter reference {ctx_ref!r} does not resolve to a "
                    "Bundle Encounter",
                    resource_type=_str(resource.get("resourceType")),
                    resource_id=rid,
                )

    # 9-11. coverage and type matching against the expected canonical records
    bundle_clinical_ids = {resource_id for resource_id, _ in clinical}
    expected_clinical_ids = set(mapped.clinical_resource_types)
    for missing in sorted(expected_clinical_ids - bundle_clinical_ids):
        error(
            "missing-clinical-resource",
            f"expected clinical resource {missing} absent from Bundle",
            resource_id=missing,
        )
    for unexpected in sorted(bundle_clinical_ids - expected_clinical_ids):
        error(
            "unexpected-clinical-resource",
            f"unexpected clinical resource {unexpected} in Bundle",
            resource_id=unexpected,
        )
    if len(mapped.expected_record_ids) != len(clinical):
        error(
            "clinical-count-mismatch",
            f"expected {len(mapped.expected_record_ids)} clinical resources, found {len(clinical)}",
        )
    for resource_id, resource in clinical:
        expected_record_type = mapped.clinical_resource_types.get(resource_id)
        if expected_record_type is None:
            continue
        expected_fhir_type = _CLINICAL_TYPE_FOR_RECORD[expected_record_type]
        actual_type = resource.get("resourceType")
        if actual_type != expected_fhir_type:
            error(
                "resource-type-mismatch",
                f"resource {resource_id} is {actual_type!r}, expected {expected_fhir_type}",
                resource_id=resource_id,
            )

    # 12. attachment payloads
    issues.extend(_validate_attachments(bundle_json))

    # 13. deterministic ordering
    issues.extend(_validate_ordering(entries))
    return issues


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _validate_attachments(bundle_json: dict[str, object]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for resource in _resources(bundle_json):
        attachments: list[object] = []
        content = resource.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("attachment"), dict):
                    attachments.append(item["attachment"])
        presented = resource.get("presentedForm")
        if isinstance(presented, list):
            attachments.extend(presented)
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            data = attachment.get("data")
            if not isinstance(data, str):
                continue
            resource_id = resource.get("id")
            rid = resource_id if isinstance(resource_id, str) else None
            try:
                decoded = base64.b64decode(data, validate=True)
                decoded.decode("utf-8")
            except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid-attachment",
                        message=f"attachment data is not valid base64/UTF-8: {exc}",
                        validator="reference_integrity",
                        resource_type=_str(resource.get("resourceType")),
                        resource_id=rid,
                    )
                )
    return issues


def _validate_ordering(entries: list[object]) -> list[ValidationIssue]:
    order = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
            order.append(entry["resource"].get("resourceType"))
    issues: list[ValidationIssue] = []
    if not order or order[0] != "Patient":
        issues.append(
            ValidationIssue(
                severity="error",
                code="ordering-patient-first",
                message="Patient must be the first Bundle entry",
                validator="reference_integrity",
            )
        )
    # Expected block order: Patient, Encounters, then clinical resources.
    rank = {"Patient": 0, "Encounter": 1, "DocumentReference": 2, "DiagnosticReport": 2}
    ranks = [rank.get(rt, 99) for rt in order]
    if ranks != sorted(ranks):
        issues.append(
            ValidationIssue(
                severity="error",
                code="ordering-blocks",
                message=(
                    "Bundle entries are not in deterministic block order "
                    "(Patient, Encounter, clinical)"
                ),
                validator="reference_integrity",
            )
        )
    return issues


def _ref(value: object) -> str | None:
    if isinstance(value, dict):
        reference = value.get("reference")
        if isinstance(reference, str):
            return reference
    return None


def _context_encounter_refs(resource: dict[str, object]) -> list[str]:
    context = resource.get("context")
    if not isinstance(context, dict):
        return []
    encounters = context.get("encounter")
    if not isinstance(encounters, list):
        return []
    refs: list[str] = []
    for item in encounters:
        ref = _ref(item)
        if ref is not None:
            refs.append(ref)
    return refs


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None
