# Product Requirements — EHR Media Intelligence Platform

## Overview

EHR Media Intelligence is a portfolio-quality platform that turns messy,
heterogeneous electronic health record (EHR) exports into structured,
FHIR-compatible clinical documents that clinicians can explore through
AI-generated summaries and semantic search.

The platform operates exclusively on **synthetic patient data**. It is a
demonstration system and is not intended for clinical use.

## Goals

1. Demonstrate robust ingestion and normalization of messy healthcare data.
2. Demonstrate interoperability through FHIR-compatible resource mapping.
3. Demonstrate practical, safe application of AI to clinical documents
   (summarization and semantic search) with clear disclaimers.
4. Maintain production-grade engineering quality: typed code, tests, linting,
   CI, and documented architecture.

## Functional requirements

### 1. Ingestion — implemented

- Ingest synthetic EHR records supplied as JSON, CSV, and plain text.
- Tolerate messy input: inconsistent field names, mixed date formats, missing
  values, and free-text noise.

Delivered as a deterministic command-line pipeline
(`python -m app.ingestion.cli`) with structured reports for accepted,
duplicate, rejected, and identity-conflicting records.

### 2. Cleaning and normalization — implemented

- Clean and normalize ingested records into strict Pydantic v2 domain models.
- Validation failures must be captured and reported, not silently discarded.

Includes explicit rules for dates, gender, MRNs, names, and clinical text,
plus exact-duplicate detection and a conservative patient-identity policy
(see `architecture.md`).

### 3. Audit logging — implemented

- Record a per-record audit log covering ingestion outcome, applied
  transformations, and validation issues.

Every normalization decision is recorded as a structured audit entry on the
affected patient or record; the ingestion report contains per-record
outcomes.

### 4. FHIR mapping — implemented

- Map normalized records to FHIR-compatible resources:
  - `Patient`
  - `Encounter`
  - `DocumentReference`
  - `DiagnosticReport`
  - `Bundle`
- Restrict usage to fields shared with FHIR R4 4.0.1 (see
  `architecture.md` for the R4/R4B compatibility decision).

Delivered as deterministic, idempotent mapping of one Bundle per patient, with
three validation layers (`fhir.resources`, reference integrity, and a scoped
R4 compatibility guard) and SQLite persistence of Bundles and validation
reports. The scoped guard is not a substitute for the official HL7 FHIR
Validator, and official R4 conformance validation is not claimed as tested.

### 5. Clinical summarization — implemented

- Generate clinical summaries of FHIR document content through the Anthropic
  API.
- Cache summaries so repeated requests do not re-invoke the API.
- Summaries are assistive only and must be presented with a clinical
  disclaimer.

Delivered as a cache-aware CLI over stored valid Bundles: deterministic
evidence extraction, a versioned safety prompt, structured-output validation
against a fixed Pydantic schema, an application-controlled disclaimer and hard
200-word limit enforced in code, a SQLite cache keyed on the Bundle hash /
model / prompt version, and deterministic quality checks. The API key and model
are configured via `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`; cached summaries
are readable without a key. Summaries are assistive and require human review.

### 6. Embeddings and semantic search — planned

- Embed FHIR document text and generated summaries using
  sentence-transformers.
- Store embeddings in a persistent ChromaDB collection.
- Expose semantic search over documents and summaries via a FastAPI
  `POST /search` endpoint.

### 7. Clinician-facing interface — planned

- Provide a React + Tailwind CSS web interface for clinicians to search and
  review documents and summaries.
- Communicate clearly that all data is synthetic and the tool is not for
  clinical decision-making.

## Non-functional requirements

- **Data safety**: synthetic patient data only; never real patient data.
- **Secrets**: configuration via environment variables; no secrets in the
  repository.
- **Testing**: automated tests run without network access; external services
  are injected and mocked.
- **Quality gates**: linting, formatting, static type checking, and tests run
  in CI for both backend and frontend.
- **Traceability**: every ingested record has an auditable processing trail.

## Out of scope

- Real EHR system integrations (HL7 v2 feeds, live FHIR servers).
- Authentication, authorization, and multi-tenancy.
- Clinical decision support of any kind.
- Handling of real protected health information.
