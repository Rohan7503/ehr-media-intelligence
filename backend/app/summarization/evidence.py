"""Deterministic extraction of compact prompt evidence from a stored Bundle.

Converts a stored FHIR Bundle (parsed JSON) into a small, ordered payload of
clinical text with resource IDs retained, so the generated summary can be
checked against its sources. The complete serialized Bundle and raw base64
attachment payloads are never sent to the provider — attachments are decoded
to text here.
"""

import base64
import binascii
import json

from pydantic import BaseModel, Field

#: Per-record text is truncated to keep the prompt compact and bounded.
MAX_RECORD_TEXT_CHARS = 1500


class EvidenceRecord(BaseModel):
    """One clinical record distilled for the prompt."""

    resource_id: str
    resource_type: str
    title: str
    date: str | None = None
    text: str


class PatientEvidence(BaseModel):
    """Compact, ordered evidence for one patient's Bundle."""

    patient_id: str
    records: list[EvidenceRecord] = Field(default_factory=list)
    #: All resource IDs present in the Bundle, for citation validation.
    resource_ids: list[str] = Field(default_factory=list)


def _decode_attachment(data: str) -> str | None:
    """Decode a base64 attachment payload to text, or ``None`` if invalid."""
    try:
        return base64.b64decode(data, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


def _attachment_text(resource: dict[str, object]) -> str | None:
    content = resource.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("attachment"), dict):
                data = item["attachment"].get("data")
                if isinstance(data, str):
                    decoded = _decode_attachment(data)
                    if decoded is not None:
                        return decoded
    return None


def _presented_form_text(resource: dict[str, object]) -> str | None:
    presented = resource.get("presentedForm")
    if isinstance(presented, list):
        for item in presented:
            if isinstance(item, dict) and isinstance(item.get("data"), str):
                decoded = _decode_attachment(item["data"])
                if decoded is not None:
                    return decoded
    return None


def _codeable_text(value: object) -> str:
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text
    return ""


def extract_patient_evidence(patient_id: str, bundle_json: str) -> PatientEvidence:
    """Extract compact, ordered evidence from a stored Bundle JSON string."""
    bundle = json.loads(bundle_json)
    entries = bundle.get("entry", []) if isinstance(bundle, dict) else []

    records: list[EvidenceRecord] = []
    resource_ids: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            continue
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        if not isinstance(resource_type, str) or not isinstance(resource_id, str):
            continue
        resource_ids.append(resource_id)

        if resource_type == "DocumentReference":
            text = _attachment_text(resource) or ""
            title = _codeable_text(resource.get("type"))
            date = _context_period_start(resource)
        elif resource_type == "DiagnosticReport":
            conclusion = resource.get("conclusion")
            text = conclusion if isinstance(conclusion, str) else ""
            if not text:
                text = _presented_form_text(resource) or ""
            title = _codeable_text(resource.get("code"))
            effective = resource.get("effectiveDateTime")
            date = effective if isinstance(effective, str) else None
        else:
            continue

        records.append(
            EvidenceRecord(
                resource_id=resource_id,
                resource_type=resource_type,
                title=title,
                date=date,
                text=text[:MAX_RECORD_TEXT_CHARS],
            )
        )

    return PatientEvidence(patient_id=patient_id, records=records, resource_ids=resource_ids)


def _context_period_start(resource: dict[str, object]) -> str | None:
    context = resource.get("context")
    if isinstance(context, dict):
        period = context.get("period")
        if isinstance(period, dict):
            start = period.get("start")
            if isinstance(start, str):
                return start
    return None
