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

### 1. Ingestion

- Ingest synthetic EHR records supplied as JSON, CSV, and plain text.
- Tolerate messy input: inconsistent field names, mixed date formats, missing
  values, and free-text noise.

### 2. Cleaning and normalization

- Clean and normalize ingested records into strict Pydantic v2 domain models.
- Validation failures must be captured and reported, not silently discarded.

### 3. Audit logging

- Record a per-record audit log covering ingestion outcome, applied
  transformations, and validation issues.

### 4. FHIR mapping

- Map normalized records to FHIR-compatible resources:
  - `Patient`
  - `Encounter`
  - `DocumentReference`
  - `DiagnosticReport`
  - `Bundle`
- Restrict usage to fields shared with FHIR R4 4.0.1 (see
  `architecture.md` for the R4/R4B compatibility decision).

### 5. Clinical summarization

- Generate clinical summaries of FHIR document content through the Anthropic
  API.
- Cache summaries so repeated requests do not re-invoke the API.
- Summaries are assistive only and must be presented with a clinical
  disclaimer.

### 6. Embeddings and semantic search

- Embed FHIR document text and generated summaries using
  sentence-transformers.
- Store embeddings in a persistent ChromaDB collection.
- Expose semantic search over documents and summaries via a FastAPI
  `POST /search` endpoint.

### 7. Clinician-facing interface

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
