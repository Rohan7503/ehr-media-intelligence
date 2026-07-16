"""Stable constants for FHIR mapping.

These values are fixed so that generated Bundle content is deterministic and
byte-identical across runs. Every coded value chosen here is a documented,
verified FHIR R4 4.0.1 value; see ``docs/architecture.md`` for the mapping
assumptions and the exact limits of the R4 compatibility guard.
"""

from typing import Final
from uuid import UUID

# --- Target metadata (reported verbatim; never claims official conformance) ---
FHIR_VERSION: Final = "4.0.1"
MODEL_LIBRARY: Final = "fhir.resources"
MODEL_NAMESPACE: Final = "R4B"
COMPATIBILITY_STRATEGY: Final = "R4 field subset"

# --- Deterministic identifier namespace (UUIDv5 root) ---
# Fixed project namespace; do not regenerate. Derived once from a project URL.
NAMESPACE_UUID: Final = UUID("1e041c0b-8376-5c4d-9ba0-cbdff5dd3e5d")

# --- Project-owned identifier systems (URNs, not external terminologies) ---
MRN_SYSTEM: Final = "urn:ehr-media-intelligence:mrn"
# Source-provided diagnostic codes are preserved in this clearly project-owned
# namespace. This does NOT assert membership in LOINC, SNOMED CT, ICD, etc.
SOURCE_DIAGNOSTIC_CODE_SYSTEM: Final = "urn:ehr-media-intelligence:source-diagnostic-code"

# --- Standard HL7 identifier-type coding for a medical record number ---
IDENTIFIER_TYPE_SYSTEM: Final = "http://terminology.hl7.org/CodeSystem/v2-0203"
MRN_TYPE_CODE: Final = "MR"
MRN_TYPE_DISPLAY: Final = "Medical record number"

# --- Encounter mapping defaults ---
# The canonical ingestion model carries no encounter status or class. These
# conservative defaults are valid R4 values for the synthetic dataset:
#  - status "finished": records represent completed, historical encounters.
#  - class AMB (ambulatory): outpatient notes and reports, the dataset's nature.
ENCOUNTER_STATUS: Final = "finished"
ENCOUNTER_CLASS_SYSTEM: Final = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
ENCOUNTER_CLASS_CODE: Final = "AMB"
ENCOUNTER_CLASS_DISPLAY: Final = "ambulatory"

# --- Resource status defaults (required R4 fields) ---
DOCUMENT_REFERENCE_STATUS: Final = "current"
DIAGNOSTIC_REPORT_STATUS: Final = "final"

# --- Attachment ---
ATTACHMENT_CONTENT_TYPE: Final = "text/plain"

# --- Bundle ---
BUNDLE_TYPE: Final = "collection"

SUPPORTED_RESOURCE_TYPES: Final = frozenset(
    {"Patient", "Encounter", "DocumentReference", "DiagnosticReport", "Bundle"}
)
