"""Versioned clinical-summary prompt and structured-output tool schema.

Kept in a dedicated module so the exact safety rules can be reviewed and
versioned. Bump ``PROMPT_VERSION`` whenever the wording changes so cached
summaries generated under an older prompt are not reused.
"""

import json

from app.summarization.evidence import PatientEvidence
from app.summarization.summary import NOT_DOCUMENTED, WORD_LIMIT

PROMPT_VERSION = "clinical-summary-v1"

#: Name of the forced structured-output tool.
TOOL_NAME = "record_clinical_summary"

SYSTEM_PROMPT = f"""\
You are a careful clinical documentation assistant. You produce a concise \
structured summary of a single patient strictly from the FHIR-derived records \
supplied in the user message.

Rules you must follow exactly:
- Use only facts explicitly present in the supplied records. Do not use outside \
knowledge.
- Provide: the chief concern, key diagnoses, recent imaging/lab/media records, \
and flagged anomalies.
- When the supplied records do not support a section, use the exact phrase \
"{NOT_DOCUMENTED}" for that section.
- Do not provide treatment recommendations or next steps.
- Do not infer or state a diagnosis from an abnormal result; report only what \
is documented.
- Do not exaggerate certainty; set confidence to "low" when evidence is thin.
- Reference only the FHIR resource IDs that appear in the supplied records, in \
the source_resource_ids field.
- Keep the complete rendered summary below {WORD_LIMIT} words; be terse.
- Return only the structured tool output; do not write prose outside the tool.
- Do not write a disclaimer; the application adds a fixed disclaimer itself.
"""

#: JSON Schema for the forced tool call. Mirrors ``SummaryDraft`` exactly. The
#: disclaimer, patient_id, and word_count are added by the application and are
#: intentionally absent here.
TOOL_INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "chief_concern": {
            "type": "string",
            "description": f'The main documented concern, or "{NOT_DOCUMENTED}".',
        },
        "key_diagnoses": {
            "type": "array",
            "items": {"type": "string"},
            "description": f'Documented diagnoses, or ["{NOT_DOCUMENTED}"] if none.',
        },
        "recent_media_records": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Recent imaging, lab, or media records with their dates, or "
                f'["{NOT_DOCUMENTED}"] if none.'
            ),
        },
        "flagged_anomalies": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                f'Explicitly documented abnormal findings, or ["{NOT_DOCUMENTED}"] if none.'
            ),
        },
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Confidence given the available evidence.",
        },
        "source_resource_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "IDs of the supplied FHIR resources this summary draws on.",
        },
    },
    "required": [
        "chief_concern",
        "key_diagnoses",
        "recent_media_records",
        "flagged_anomalies",
        "confidence",
        "source_resource_ids",
    ],
    "additionalProperties": False,
}


def build_user_message(evidence: PatientEvidence) -> str:
    """Render the compact evidence payload as the user message."""
    payload = {
        "patient_id": evidence.patient_id,
        "records": [record.model_dump() for record in evidence.records],
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "Summarize the following patient strictly from these FHIR-derived "
        "records. Cite only the resource_id values shown here.\n\n" + body
    )
