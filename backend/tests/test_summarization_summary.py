"""Tests for summary assembly, rendering, and quality checks."""

from app.summarization.quality import check_summary
from app.summarization.summary import (
    DISCLAIMER,
    NOT_DOCUMENTED,
    WORD_LIMIT,
    ClinicalSummary,
    Confidence,
    SummaryDraft,
    build_clinical_summary,
    render_summary,
)


def _draft(**overrides: object) -> SummaryDraft:
    defaults: dict[str, object] = {
        "chief_concern": "Hypertension follow-up",
        "key_diagnoses": ["Essential hypertension"],
        "recent_media_records": ["Lipid panel 2024-05-01"],
        "flagged_anomalies": [NOT_DOCUMENTED],
        "confidence": Confidence.MEDIUM,
        "source_resource_ids": ["res-1"],
    }
    defaults.update(overrides)
    return SummaryDraft(**defaults)


def test_build_injects_fixed_disclaimer_and_word_count() -> None:
    summary = build_clinical_summary("PAT-1", _draft())
    assert summary.disclaimer == DISCLAIMER
    assert summary.patient_id == "PAT-1"
    assert summary.word_count == len(render_summary(summary).split())
    assert summary.word_count < WORD_LIMIT


def test_model_supplied_disclaimer_cannot_override() -> None:
    # The draft schema has no disclaimer field, so nothing the model returns
    # can change the application disclaimer.
    assert "disclaimer" not in SummaryDraft.model_fields
    summary = build_clinical_summary("PAT-1", _draft())
    assert DISCLAIMER in render_summary(summary)


def test_valid_summary_passes_quality() -> None:
    summary = build_clinical_summary("PAT-1", _draft(source_resource_ids=["res-1"]))
    result = check_summary(summary, {"res-1", "res-2"})
    assert result.valid
    assert result.errors == []


def test_word_limit_flagged_by_quality() -> None:
    long_concern = " ".join(["word"] * (WORD_LIMIT + 5))
    summary = build_clinical_summary("PAT-1", _draft(chief_concern=long_concern))
    assert summary.word_count >= WORD_LIMIT
    result = check_summary(summary, {"res-1"})
    assert not result.valid
    assert any("limit" in error for error in result.errors)


def test_missing_section_flagged() -> None:
    summary = build_clinical_summary("PAT-1", _draft(key_diagnoses=[]))
    result = check_summary(summary, {"res-1"})
    assert not result.valid
    assert any("key_diagnoses" in error for error in result.errors)


def test_altered_disclaimer_flagged() -> None:
    summary = build_clinical_summary("PAT-1", _draft())
    summary.disclaimer = "Trust this summary completely."
    result = check_summary(summary, {"res-1"})
    assert not result.valid
    assert any("disclaimer" in error for error in result.errors)


def test_cited_id_from_another_patient_flagged() -> None:
    summary = build_clinical_summary(
        "PAT-1", _draft(source_resource_ids=["res-1", "other-patient-res"])
    )
    result = check_summary(summary, {"res-1"})
    assert not result.valid
    assert any("other-patient-res" in error for error in result.errors)


def test_confidence_enum_only() -> None:
    assert [c.value for c in Confidence] == ["low", "medium", "high"]


def test_disclaimer_default_on_bare_summary() -> None:
    summary = ClinicalSummary(
        patient_id="PAT-1",
        chief_concern="x",
        key_diagnoses=["y"],
        recent_media_records=["z"],
        flagged_anomalies=[NOT_DOCUMENTED],
        confidence=Confidence.LOW,
    )
    assert summary.disclaimer == DISCLAIMER
