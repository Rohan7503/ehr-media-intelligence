"""Scoped FHIR R4 compatibility guard.

This guard is intentionally narrow: it verifies that the JSON this project's
mapper emits stays within a documented allowlist of FHIR R4 4.0.1 fields and
resource types. It is **not** a replacement for the official HL7 FHIR
Validator and does not attempt to implement the full specification. It exists
to catch accidental use of an R4B-only field, an unexpected resource type, or
a profile/extension the mapper should never emit.

The allowlist below describes exactly the shapes ``app.fhir.mapper`` produces.
Every emitted key must appear in the allowlist for its structure; any other
key (including ``extension``, ``modifierExtension``, ``meta``, or an
R4B-specific field) is reported as an error-severity issue.
"""

from typing import Final

from app.fhir import constants
from app.fhir.report import ValidationIssue

# Each structure maps to (leaf keys, {complex field: (child structure, is_list)}).
# The union of both is the complete set of allowed keys for that structure.
_Schema = dict[str, tuple[set[str], dict[str, tuple[str, bool]]]]

SCHEMA: Final[_Schema] = {
    "Patient": (
        {"resourceType", "id", "gender", "birthDate"},
        {"identifier": ("Identifier", True), "name": ("HumanName", True)},
    ),
    "Encounter": (
        {"resourceType", "id", "status"},
        {
            "class": ("Coding", False),
            "subject": ("Reference", False),
            "period": ("Period", False),
        },
    ),
    "DocumentReference": (
        {"resourceType", "id", "status"},
        {
            "subject": ("Reference", False),
            "type": ("CodeableConcept", False),
            "content": ("DocumentReferenceContent", True),
            "context": ("DocumentReferenceContext", False),
        },
    ),
    "DiagnosticReport": (
        {"resourceType", "id", "status", "effectiveDateTime", "conclusion"},
        {
            "identifier": ("Identifier", True),
            "code": ("CodeableConcept", False),
            "subject": ("Reference", False),
            "encounter": ("Reference", False),
            "presentedForm": ("Attachment", True),
        },
    ),
    "Identifier": (
        {"use", "system", "value"},
        {"type": ("CodeableConcept", False)},
    ),
    "CodeableConcept": ({"text"}, {"coding": ("Coding", True)}),
    "Coding": ({"system", "code", "display"}, {}),
    "HumanName": ({"family", "given"}, {}),
    "Reference": ({"reference"}, {}),
    "Period": ({"start", "end"}, {}),
    "Attachment": ({"contentType", "data", "title"}, {}),
    "DocumentReferenceContent": (
        set(),
        {"attachment": ("Attachment", False)},
    ),
    "DocumentReferenceContext": (
        set(),
        {"encounter": ("Reference", True), "period": ("Period", False)},
    ),
}


def check_bundle_compatibility(bundle_json: dict[str, object]) -> list[ValidationIssue]:
    """Verify emitted Bundle JSON stays within the R4-compatible allowlist."""
    issues: list[ValidationIssue] = []
    top_type = bundle_json.get("resourceType")
    if top_type != "Bundle":
        issues.append(
            ValidationIssue(
                severity="error",
                code="unexpected-bundle-type",
                message=f"top-level resourceType is not Bundle: {top_type!r}",
                validator="r4_compatibility",
            )
        )
        return issues

    allowed_bundle_keys = {"resourceType", "id", "type", "entry"}
    for key in bundle_json:
        if key not in allowed_bundle_keys:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="disallowed-field",
                    message=f"Bundle contains field not in the R4 allowlist: '{key}'",
                    validator="r4_compatibility",
                    resource_type="Bundle",
                    location=key,
                )
            )

    entries = bundle_json.get("entry")
    if isinstance(entries, list):
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            for key in entry:
                if key not in {"fullUrl", "resource"}:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="disallowed-field",
                            message=f"Bundle entry has field not in the R4 allowlist: '{key}'",
                            validator="r4_compatibility",
                            location=f"entry[{index}].{key}",
                        )
                    )
            resource = entry.get("resource")
            if isinstance(resource, dict):
                _check_resource(resource, index, issues)
    return issues


def _check_resource(resource: dict[str, object], index: int, issues: list[ValidationIssue]) -> None:
    resource_type = resource.get("resourceType")
    if (
        not isinstance(resource_type, str)
        or resource_type not in constants.SUPPORTED_RESOURCE_TYPES
    ):
        issues.append(
            ValidationIssue(
                severity="error",
                code="unsupported-resource-type",
                message=f"entry[{index}] has unsupported resourceType: {resource_type!r}",
                validator="r4_compatibility",
                location=f"entry[{index}].resource.resourceType",
            )
        )
        return
    _check_structure(
        resource,
        resource_type,
        f"entry[{index}].resource",
        resource_type,
        issues,
    )


def _check_structure(
    value: dict[str, object],
    structure: str,
    location: str,
    resource_type: str,
    issues: list[ValidationIssue],
) -> None:
    schema = SCHEMA.get(structure)
    if schema is None:  # pragma: no cover - guards against schema gaps
        issues.append(
            ValidationIssue(
                severity="error",
                code="unknown-structure",
                message=f"no R4 allowlist defined for structure '{structure}'",
                validator="r4_compatibility",
                resource_type=resource_type,
                location=location,
            )
        )
        return
    leaf_keys, complex_fields = schema
    allowed = leaf_keys | set(complex_fields)
    for key, child in value.items():
        if key not in allowed:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="disallowed-field",
                    message=(f"'{structure}' contains field not in the R4 allowlist: '{key}'"),
                    validator="r4_compatibility",
                    resource_type=resource_type,
                    location=f"{location}.{key}",
                )
            )
            continue
        if key in complex_fields:
            child_structure, is_list = complex_fields[key]
            children = child if isinstance(child, list) else [child]
            for child_index, item in enumerate(children):
                if isinstance(item, dict):
                    suffix = f"[{child_index}]" if is_list else ""
                    _check_structure(
                        item,
                        child_structure,
                        f"{location}.{key}{suffix}",
                        resource_type,
                        issues,
                    )
