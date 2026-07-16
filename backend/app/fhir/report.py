"""Structured validation and pipeline report models.

These Pydantic v2 models are JSON-serializable and deterministic. A Bundle is
considered valid only when it has no ``error``-severity issues; warnings and
information remain visible but never flip a Bundle to invalid.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.fhir import constants

Severity = Literal["error", "warning", "information"]
ValidatorSource = Literal["fhir.resources", "reference_integrity", "r4_compatibility"]
StorageOutcome = Literal["inserted", "updated", "unchanged"]


class ValidationIssue(BaseModel):
    """A single validation finding from one of the validation layers."""

    severity: Severity
    code: str
    message: str
    validator: ValidatorSource
    resource_type: str | None = None
    resource_id: str | None = None
    location: str | None = None


class StorageResult(BaseModel):
    """The outcome of persisting one patient's Bundle and report."""

    patient_id: str
    bundle_id: str
    outcome: StorageOutcome


class PatientBundleValidation(BaseModel):
    """Per-patient validation outcome for one Bundle."""

    patient_id: str
    bundle_id: str
    fhir_version: str = constants.FHIR_VERSION
    model_namespace: str = constants.MODEL_NAMESPACE
    valid: bool
    resource_counts: dict[str, int] = Field(default_factory=dict)
    issues: list[ValidationIssue] = Field(default_factory=list)


class FHIRPipelineReport(BaseModel):
    """Aggregate report for one FHIR pipeline run."""

    fhir_version: str = constants.FHIR_VERSION
    model_library: str = constants.MODEL_LIBRARY
    model_namespace: str = constants.MODEL_NAMESPACE
    compatibility_strategy: str = constants.COMPATIBILITY_STRATEGY
    patient_count: int = 0
    bundle_count: int = 0
    valid_bundle_count: int = 0
    invalid_bundle_count: int = 0
    resource_totals: dict[str, int] = Field(default_factory=dict)
    validations: list[PatientBundleValidation] = Field(default_factory=list)
    storage_results: list[StorageResult] = Field(default_factory=list)
