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

### Feeding FHIR mapping

The canonical `Patient` and `ClinicalRecord` models are the sole input to the
`fhir` module: `Patient` → FHIR Patient, `ClinicalRecord` → DocumentReference
or DiagnosticReport (by record type) plus Encounter references, bundled per
patient. Because ingestion already produces clean, deduplicated,
identity-resolved models, FHIR mapping is a pure transformation with no
cleaning logic of its own.

## FHIR mapping and persistence architecture

### Mapper boundaries

All `fhir.resources.R4B` imports live under `backend/app/fhir/`; no other
package imports the FHIR model library. The mapper
(`app.fhir.mapper`) is pure and read-only: it consumes canonical `Patient` and
`ClinicalRecord` models and returns `fhir.resources.R4B` resources without
mutating its inputs. Coded defaults and identifier systems are centralized in
`app.fhir.constants`.

### Deterministic ID strategy

Every resource ID is a UUIDv5 (`app.fhir.identifiers`) derived from a fixed
project namespace UUID and a canonical name string of the resource type plus
the relevant canonical IDs (patient, and encounter or record where
applicable). Consequences:

- Same canonical input → same IDs, references, and `fullUrl`s across runs.
- Document and diagnostic mappings include the resource-type name in the
  derivation, so they never collide.
- A UUID string satisfies the FHIR `id` restriction `[A-Za-z0-9-.]{1,64}`.
- No `UUIDv4`/random IDs and no timestamps enter Bundle content, so serialized
  Bundles are byte-identical across runs.

### Bundle layout and ordering

One `collection` Bundle per patient. Entry order is deterministic: the Patient
first, then Encounters in resource-ID order, then clinical resources sorted by
`(dated-first, date, record type, record ID)`. Undated records are still
included, sorted after dated ones. Each entry's `fullUrl` is the
`urn:uuid:<id>` form of its resource ID.

### Subject and encounter reference design

References are literal `urn:uuid:<id>` strings that exactly match the target
entry's `fullUrl` (built by `app.fhir.references` so mapper and validator
agree on the exact form). Clinical resources reference the Bundle Patient as
`subject`; DiagnosticReport uses `encounter`, and DocumentReference uses
`context.encounter`. Encounter periods are derived from associated record
dates (earliest start, latest end) or omitted when no date exists.

### Validation layers

`app.fhir.validator` runs three independent layers and returns a structured
`PatientBundleValidation` (`app.fhir.report`):

1. **`fhir.resources`** — re-parses the serialized Bundle through the library
   models; any `ValidationError` becomes structured issues rather than a raw
   traceback.
2. **Reference integrity** — a Pydantic-independent validator covering the
   13 Bundle invariants (single Patient; present, unique resource IDs; unique
   `fullUrl`s; resolvable subject/encounter references; complete and exclusive
   coverage of the expected canonical records; matching resource types; valid
   base64/UTF-8 attachment payloads; deterministic block ordering). Broken
   references are reported, never repaired.
3. **R4 compatibility guard** (`app.fhir.compatibility`) — see below.

A Bundle is valid only when it has no `error`-severity issues. Warnings and
information remain visible but do not mark a Bundle invalid.

### SQLite schema and repository boundaries

Two SQLAlchemy 2 typed declarative tables (`app.persistence.models`), kept
separate from domain/FHIR models:

- `fhir_bundle` — `patient_id` (PK), `bundle_id` (unique), `bundle_hash`,
  `bundle_json` (canonical JSON text), `fhir_version`, `model_namespace`,
  `valid`.
- `validation_report` — `patient_id` (PK), `bundle_id`, `report_json`.

`patient_id` as primary key guarantees exactly one current Bundle and one
current report per patient. The engine is created explicitly and tables are
created by `init_db`; nothing touches a database at import time. All access
goes through `BundleRepository` (`upsert_bundle_and_report`,
`get_bundle_by_patient_id`, `list_bundle_metadata`, `count_bundles`).

### Idempotent upsert behavior

`upsert_bundle_and_report` compares the incoming Bundle hash to the stored row:
absent → insert (`inserted`); same hash → reuse (`unchanged`); different hash →
replace the Bundle and its report (`updated`). Writes run in a transaction and
roll back cleanly on failure (raising `StorageError`). Ingestion duplicates,
rejections, and identity conflicts are never written to these tables.

### Pipeline

`app.fhir.pipeline.run_fhir_pipeline` consumes the ingestion `PipelineResult`
(never mutating it), groups accepted records by patient, and maps, validates,
persists, and optionally exports one Bundle per patient. If one patient fails
to map or validate, the others still process; the failure is recorded in the
aggregate `FHIRPipelineReport`. The `app.fhir.cli` entry point wires ingestion
to this pipeline and returns distinct exit codes for success, invalid Bundles,
and unrecoverable failures.

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

### Limits of the R4 compatibility guard

The guard in `app.fhir.compatibility` maintains an explicit allowlist of the
resource types and fields this project emits (Patient, Encounter,
DocumentReference, DiagnosticReport, Bundle, and the nested structures they
use). It rejects any emitted field outside that allowlist — including
R4B-only fields — any unsupported `resourceType`, and any profile or extension
the mapper should never produce.

Its scope is deliberately narrow. It validates **only this project's output
shape**; it does not implement FHIR cardinality rules, value-set binding,
invariants, terminology validation, or the full specification. It is a
guardrail against accidental drift out of the R4-compatible field subset, not
a conformance validator. R4B model validation through `fhir.resources` is not,
by itself, exact official R4 conformance validation. The project does not
claim the official HL7 FHIR Validator was run; exported Bundles can be checked
against it optionally (see `README.md`).

### FHIR handoff to future summarization and search phases

The stored Bundles and the canonical `ClinicalRecord` text are the inputs to
the planned summarization and search phases: summaries will be generated from
resource text and cached in SQLite, and document text plus summaries will be
embedded into ChromaDB. Deterministic resource IDs and Bundle hashes give
those phases stable keys to attach summaries and embeddings to, and to detect
when a Bundle has changed and its derived artifacts must be recomputed.

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
