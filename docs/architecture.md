# Architecture — EHR Media Intelligence Platform

## Component flow

```
synthetic EHR files (JSON / CSV / text)
        │
        ▼
  Ingestion ──────────────► Audit log (SQLite)
        │  parse, clean,
        │  normalize
        ▼
  Pydantic v2 domain models
        │
        ▼
  FHIR mapping (Patient, Encounter, DocumentReference,
                DiagnosticReport, Bundle)
        │
        ├────────────────► Persistence (SQLite via SQLAlchemy 2)
        │
        ▼
  Summarization (Anthropic API, cached in SQLite)
        │
        ▼
  Embeddings (sentence-transformers)
        │
        ▼
  Vector store (persistent ChromaDB)
        │
        ▼
  FastAPI  POST /search
        │
        ▼
  React + Tailwind CSS clinician interface (Fetch API)
```

## Mandatory technologies

Backend:

- Python 3.11
- FastAPI
- Pydantic v2
- fhir.resources
- sentence-transformers
- ChromaDB
- SQLite (via SQLAlchemy 2)
- pytest

Frontend:

- React with TypeScript
- Vite
- Tailwind CSS
- Native Fetch API

Supporting tooling: Ruff (lint + format), mypy, ESLint, TypeScript compiler
checks, GitHub Actions CI.

These choices are fixed. Do not substitute alternatives.

## Storage responsibilities

### SQLite (via SQLAlchemy 2)

Relational system of record:

- normalized record metadata and processing state
- per-record audit log entries
- cached clinical summaries (keyed by document identity and prompt/model
  version, so unchanged documents never re-invoke the Anthropic API)

### ChromaDB

Vector store only:

- embeddings of FHIR document text and generated summaries
- metadata needed to link a vector hit back to its SQLite/FHIR source record

ChromaDB persists to a local directory (`CHROMA_PATH`). It never holds the
authoritative copy of any record; it can be rebuilt from SQLite content at any
time.

## Planned backend module boundaries

The backend package (`backend/app/`) will grow into these modules:

| Module          | Responsibility                                              |
| --------------- | ----------------------------------------------------------- |
| `api`           | FastAPI routers, request/response schemas, HTTP concerns    |
| `core`          | configuration, dependency wiring, shared infrastructure     |
| `domain`        | normalized Pydantic v2 domain models and invariants         |
| `ingestion`     | JSON/CSV/text parsers, cleaning, normalization, audit trail |
| `fhir`          | mapping domain models to FHIR resources                     |
| `persistence`   | SQLAlchemy models, sessions, repositories (SQLite)          |
| `summarization` | Anthropic API client wrapper and summary cache              |
| `search`        | embedding generation and ChromaDB search                    |

`api`, `core`, `domain`, and `ingestion` exist today; the rest are created
when their features are implemented. External services (Anthropic client,
ChromaDB client, embedding model, database sessions) are always injected as
dependencies so tests can substitute fakes.

## Ingestion architecture

### Canonical model boundaries

The `domain` package holds the canonical intermediate representation, fully
independent of both source formats and FHIR:

- `Patient` — canonical ID (derived from the normalized MRN), source patient
  IDs, MRN, names, birth date, canonical gender, audit trail.
- `ClinicalRecord` — canonical ID, source provenance (file, format, source
  record ID), canonical patient reference, record type, title, text, record
  date, optional encounter ID and diagnostic code, content fingerprint, audit
  trail.
- `AuditEntry` — field, rule identifier, original value, normalized value,
  human-readable reason. Entries carry no timestamps so canonical output is
  byte-identical across identical runs.

`RecordType.DOCUMENT` and `RecordType.DIAGNOSTIC_REPORT` anticipate the later
FHIR mapping to DocumentReference and DiagnosticReport; no FHIR resources are
created during ingestion.

### Loader architecture

One loader function per format (`ingestion/loaders/`), each producing
format-independent `RawRecord` objects (a dict of raw string fields plus
structural issues). All alternate column/key names resolve through a single
explicit alias table in `loaders/base.py` — no scattered conditionals.

- **JSON**: a top-level array, or an object with a `records` array. Anything
  else is a file-level error; non-object entries and nested values are
  record-level issues.
- **CSV**: standard-library parser; header names map through the alias table;
  files with no recognized columns fail at file level.
- **Text**: blank-line-separated records of `KEY: value` headers with a
  multiline `TEXT:` body (format and limitations documented in
  `loaders/text_loader.py`). A blank line always ends a record, so note text
  cannot contain blank lines.

File-level parse failures are reported per file and never abort the run.

### Normalization flow

For each raw record, in order: null-marker cleanup → structural rejection
checks (loader issues, missing/invalid MRN, no meaningful clinical text,
unrecognized record type) → demographic normalization (names, birth date,
gender) → record normalization (dates, title, record ID) → fingerprint →
duplicate check → identity resolution → acceptance.

Key rules (all in `ingestion/normalizers.py`, all deterministic):

- **Dates**: `YYYY-MM-DD`, `MM/DD/YYYY` (slash values follow the US
  convention), `DD-MM-YYYY`, and ISO 8601 date-times. Two-digit years and
  impossible dates are never guessed: invalid optional dates are flagged in
  the audit trail and stored as `None`.
- **Gender**: mapped onto the FHIR-aligned enum `male | female | other |
  unknown`; `X`/nonbinary variants map to `other`; missing or unrecognized
  values become `unknown` with an audit entry. Never inferred.
- **MRN**: trim → uppercase → strip separators → drop existing `MRN` prefix →
  zero-pad numeric IDs to six digits → prefix `MRN-`. Empty results reject
  the record.
- **Text**: line endings and trailing whitespace normalized; meaningful line
  breaks preserved; clinical meaning never altered.
- **Missing fields**: optional demographics stay `None` with an audit entry;
  a missing source record ID yields a deterministic derived ID
  (`REC-<fingerprint prefix>`); a missing title is derived from the first
  text line. Values are never invented.

### Deduplication strategy

Each record gets a SHA-256 fingerprint over its normalized
content-identifying fields (MRN, record type, date part, collapsed title,
normalized text, encounter ID, diagnostic code). Formatting-only differences
— date style, whitespace, MRN styling, line endings — cannot change the
fingerprint. The first occurrence in deterministic processing order is
canonical; later occurrences are excluded and reported with a reference to
the canonical record.

### Conservative patient-identity policy

Implemented in `ingestion/identity.py`, isolated from the rest of the
pipeline:

- Records associate to a patient **only** through the exact normalized MRN.
- Records without a usable MRN are rejected, not guessed.
- A source patient ID seen with two different MRNs is a quarantined conflict.
- An MRN seen with a different birth date or family name is a quarantined
  conflict.
- Similar or identical names never merge identities.
- Compatible later records may backfill missing demographics (`None` →
  value), always audited. Differing given names and genders never overwrite
  the first observed value.

### Feeding FHIR mapping later

The canonical `Patient` and `ClinicalRecord` models are the sole input to the
future `fhir` module: `Patient` → FHIR Patient, `ClinicalRecord` →
DocumentReference or DiagnosticReport (by record type) plus Encounter
references, bundled per patient. Because ingestion already produces clean,
deduplicated, identity-resolved models, FHIR mapping stays a pure
transformation with no cleaning logic of its own.

## FHIR R4/R4B compatibility decision

Modern Pydantic v2-compatible releases of `fhir.resources` expose older
compatible resources through the **R4B** namespace
(`fhir.resources.R4B.*`) rather than an exact R4 namespace.

Decision:

- Use the current Pydantic v2-compatible `fhir.resources` release and import
  models from the R4B namespace.
- Restrict the implementation to fields shared with **FHIR R4 4.0.1** for the
  required resources (`Patient`, `Encounter`, `DocumentReference`,
  `DiagnosticReport`, `Bundle`). R4B additions are off limits.
- Isolate this decision inside the `fhir` module: no other module imports
  `fhir.resources` directly, so a future namespace change touches one module.

FHIR mapping is not implemented in the current scaffold; this section records
the decision ahead of implementation.

## Testing strategy

- **Framework**: pytest for the backend; FastAPI's `TestClient` (HTTPX) for
  endpoint tests.
- **No network in tests**: the default test suite never calls the Anthropic
  API, downloads models, or reaches any external service. External
  dependencies are injected and replaced with fakes or mocks.
- **Unit tests** cover parsing, cleaning, normalization, FHIR mapping, and
  cache behavior with synthetic fixtures under `data/synthetic/`.
- **API tests** exercise endpoints through the ASGI app in-process.
- **Static gates**: Ruff (lint + format), mypy in strict mode, ESLint, and
  `tsc` run locally and in CI.
- **CI**: GitHub Actions runs all backend and frontend gates on every push
  and pull request.

## Repository layout

```
backend/            FastAPI application, tests, pyproject.toml
frontend/           React + TypeScript + Vite + Tailwind interface
data/synthetic/     synthetic EHR fixtures (never real data)
docs/               product requirements and architecture
scripts/            development and data-generation utilities
.github/workflows/  CI pipelines
```
