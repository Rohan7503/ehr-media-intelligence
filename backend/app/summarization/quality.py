"""Deterministic quality checks for generated summaries.

These checks support the final write-up and guard against obvious failures;
they are not a substitute for clinician review. A summary that fails any check
produces error-level findings and must not be treated as valid.
"""

from pydantic import BaseModel, Field

from app.summarization.summary import (
    DISCLAIMER,
    WORD_LIMIT,
    ClinicalSummary,
    Confidence,
    render_summary,
)


class QualityResult(BaseModel):
    """Structured outcome of the deterministic quality checks."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def check_summary(summary: ClinicalSummary, bundle_resource_ids: set[str]) -> QualityResult:
    """Validate a summary against the required rules and its Bundle's IDs.

    ``bundle_resource_ids`` must be the resource IDs of *this* patient's
    Bundle only, so any cited ID not in the set is treated as a citation of a
    non-existent or another patient's resource.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not summary.chief_concern.strip():
        errors.append("chief_concern section is empty")
    for name, items in (
        ("key_diagnoses", summary.key_diagnoses),
        ("recent_media_records", summary.recent_media_records),
        ("flagged_anomalies", summary.flagged_anomalies),
    ):
        if not [item for item in items if item.strip()]:
            errors.append(f"{name} section is empty")

    word_count = summary.word_count or len(render_summary(summary).split())
    if word_count >= WORD_LIMIT:
        errors.append(f"rendered summary has {word_count} words (limit {WORD_LIMIT})")

    if summary.disclaimer != DISCLAIMER:
        errors.append("disclaimer is missing or altered")

    if summary.confidence not in Confidence:
        errors.append(f"confidence '{summary.confidence}' is not an allowed value")

    unknown_ids = [
        resource_id
        for resource_id in summary.source_resource_ids
        if resource_id not in bundle_resource_ids
    ]
    if unknown_ids:
        errors.append(
            "cited source resource IDs not present in this patient's Bundle: "
            + ", ".join(sorted(unknown_ids))
        )

    if not summary.source_resource_ids:
        warnings.append("summary cites no source resource IDs")

    return QualityResult(valid=not errors, errors=errors, warnings=warnings)
