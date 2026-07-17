# EHR Media Intelligence — Write-up

A platform that ingests messy synthetic EHR exports, normalizes them into
FHIR-compatible resources, generates cached clinical summaries, and makes
everything explorable through semantic search and a clinician-facing web UI.
Synthetic data only; not for clinical use.

## Design and Tradeoffs

- **Staged, deterministic pipeline.** Ingestion → FHIR mapping → summarization →
  search are separate CLIs over a shared SQLite database plus a persistent
  Chroma index. Each stage is deterministic and idempotent (UUIDv5 resource IDs,
  content-hash reconcile, Bundle-hash cache keys), so re-runs are safe and
  outputs are reproducible. The tradeoff is more moving parts than a single
  service, in exchange for testability and clear boundaries.
- **Conservative clinical handling.** Normalization never guesses ambiguous
  dates and never infers demographics; identity resolution merges only on exact
  MRN and quarantines conflicts. FHIR mapping preserves clinical text verbatim
  as base64 attachments and never invents terminology codes. Summaries are
  constrained to documented sections, a hard 200-word limit, and a fixed
  disclaimer — all enforced in application code, not trusted to the model.
- **R4 via R4B.** `fhir.resources` ships R4B models; the project restricts output
  to an R4-compatible field subset and enforces it with a scoped guard. This is
  pragmatic given the library, and explicitly not full HL7 conformance.
- **Search scoring.** Cosine distance → `1 - d/2`, with a small additive
  patient-level boost from the best-matching cached summary. Simple and
  explainable, at the cost of not being a learned ranker.
- **Dependency injection everywhere external.** The Anthropic provider, Chroma
  index, embedder, and DB session are injected, so tests use fakes and make no
  network calls and need no API key.

## Improvements With More Time

- Incremental, event-driven indexing instead of full reconcile; batch embedding.
- A learned or hybrid (lexical + vector) ranker and query highlighting.
- Streaming summary generation, richer confidence calibration, and per-section
  source citations surfaced in the UI.
- AuthN/AuthZ, pagination, and rate limiting on the API.
- Frontend component tests (Vitest + Testing Library) and end-to-end tests.
- Official HL7 FHIR Validator wired into an optional CI job.

## FHIR and Clinical Concepts Researched

- FHIR R4 vs. R4B differences for Patient, Encounter, DocumentReference,
  DiagnosticReport, and Bundle, and how `fhir.resources` exposes them.
- Bundle `collection` semantics, `urn:uuid:` fullUrl references, and internal
  reference integrity.
- Attachment/base64 encoding for clinical text and DiagnosticReport
  `presentedForm` / `conclusion`.
- Administrative gender and MRN identifier conventions; encounter status/class
  value sets (conservative documented defaults for synthetic data).
- Not asserting external terminologies (LOINC/SNOMED/ICD) for unverified codes.

## Summary Quality Validation

The production Anthropic integration is implemented (real SDK, forced tool-call
structured output, typed error handling, one bounded retry). Automated tests use
a **fake provider** and make **no network calls**. **A live provider call was not
run because trial API credits were unavailable.**

Validation covered summary **structure** (all required sections), **source
references** (every cited resource ID must exist in the patient's Bundle),
**word count** (< 200, enforced in code), **disclaimer** (fixed, model cannot
alter), and **caching** (keyed by patient, Bundle hash, model, and prompt
version; cache hits avoid provider calls). A representative **evidence review**
of three synthetic patients confirmed each summary was grounded in the source
records, introduced no unsupported diagnoses, and correctly reported the absence
of abnormal findings as "Not documented" rather than fabricating anomalies (all
PASS; see `docs/validation.md`).

This was **developer validation, not clinician validation.**
