# EHR Media Intelligence

A platform that ingests messy synthetic electronic health record (EHR)
exports, normalizes them into FHIR-compatible resources, and makes them
explorable through AI-generated clinical summaries and semantic search.

> **Synthetic data only.** This project operates exclusively on synthetic
> patient data. It has never touched real patient records.
>
> **Not for clinical use.** This is a demonstration system. Its summaries and
> search results are assistive artifacts of a portfolio project and must not
> inform clinical decisions.

## Status

**Ingestion, FHIR normalization, and cached summarization complete.** The
repository structure, backend API skeleton (`GET /health`), frontend
application shell, tooling, CI, the ingestion and cleaning pipeline, FHIR
R4-compatible mapping with Bundle validation and SQLite persistence, and
cached clinical summarization via the Anthropic API are in place. Embeddings
and search are documented in
[docs/product-requirements.md](docs/product-requirements.md) but not yet
implemented.

## Architecture

Synthetic JSON/CSV/text records are ingested, cleaned into Pydantic v2 domain
models (with a per-record audit log), and mapped to FHIR-compatible resources
(Patient, Encounter, DocumentReference, DiagnosticReport, Bundle). Clinical
summaries are generated through the Anthropic API and cached in SQLite.
Document text and summaries are embedded with sentence-transformers and stored
in persistent ChromaDB, exposed via a FastAPI `POST /search` endpoint and a
React + Tailwind CSS clinician interface.

See [docs/architecture.md](docs/architecture.md) for the component flow,
storage responsibilities, module boundaries, and the FHIR R4/R4B compatibility
decision.

| Layer     | Technology                                                        |
| --------- | ----------------------------------------------------------------- |
| Backend   | Python 3.11, FastAPI, Pydantic v2, fhir.resources, SQLAlchemy 2   |
| AI        | Anthropic API (summaries), sentence-transformers (embeddings)     |
| Storage   | SQLite (records, audit log, summary cache), ChromaDB (vectors)    |
| Frontend  | React, TypeScript, Vite, Tailwind CSS, native Fetch API           |
| Quality   | Ruff, mypy, pytest, ESLint, tsc, GitHub Actions                   |

## Backend setup

Requires Python 3.11.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

The API serves `GET /health` at http://127.0.0.1:8000/health.

Configuration is read from environment variables (or a local `.env` file).
Copy `.env.example` to `.env` and adjust as needed; no variables are required
to run the scaffold.

## Ingestion pipeline

The ingestion pipeline turns messy synthetic EHR exports into canonical,
audited Pydantic models.

**Supported formats** (discovered recursively; other files are skipped with a
report):

- **JSON** (`.json`) — a top-level array of records, or an object with a
  `records` array. Common alternate key names are supported.
- **CSV** (`.csv`) — header-based, with an explicit alias table for common
  alternate column names (`Medical Record Number`, `Note Text`, …).
- **Plain text** (`.txt`) — blank-line-separated records with `KEY: value`
  headers and a multiline `TEXT:` body; the exact format is documented in
  `backend/app/ingestion/loaders/text_loader.py`.

**Generate the synthetic dataset** (deterministic; repeated runs are
byte-identical):

```bash
python scripts/generate_synthetic_data.py
```

This writes 66 raw records across `data/synthetic/{json,csv,text}/`,
deliberately including messy date/gender/MRN variants, missing fields,
cross-format duplicates, identity conflicts, and invalid records. All content
is fictional.

**Run the pipeline** (from `backend/`, with the virtual environment active):

```bash
python -m app.ingestion.cli ../data/synthetic --output-dir ../data/generated
```

Output (all deterministic JSON, written to the `--output-dir`, which is
git-ignored):

- `patients.json` — canonical patients with audit trails
- `records.json` — accepted canonical records with audit trails
- `ingestion_report.json` — counts, skipped files, file errors, per-record
  outcomes, duplicates, rejections, and identity conflicts

**How messy data is handled:**

- Every normalization decision (date reformatting, MRN canonicalization,
  gender mapping, derived IDs and titles, backfilled demographics) is
  recorded as a structured audit entry on the patient or record.
- Exact duplicates are detected by a content fingerprint that ignores
  formatting-only differences; the first occurrence wins and later copies are
  reported with a reference to the canonical record.
- Identity is resolved conservatively by exact normalized MRN only.
  Contradictory identifiers (one source patient ID with two MRNs, or one MRN
  with two birth dates or family names) are quarantined as structured
  conflicts — never merged by name similarity.
- Invalid individual records are rejected with reasons and never abort the
  run; genuinely ambiguous dates are flagged rather than guessed.

## FHIR normalization

Accepted canonical patients and records are mapped to FHIR R4-compatible
resources and grouped into one Bundle per patient.

**Resource mappings:**

| Canonical                     | FHIR resource        | Notes                                             |
| ----------------------------- | -------------------- | ------------------------------------------------- |
| patient                       | Patient              | MRN identifier, name, gender, birthDate           |
| record (`document`)           | DocumentReference    | clinical text as a base64 `text/plain` attachment |
| record (`diagnostic_report`)  | DiagnosticReport     | text-only `code`, `conclusion`, `presentedForm`   |
| canonical encounter ID        | Encounter            | one per unique ID; period derived from record dates |
| patient + its records         | Bundle (`collection`) | Patient first, then Encounters, then clinical resources |

Resource IDs and Bundle entry `fullUrl` values are deterministic UUIDv5
identifiers, and no timestamps enter Bundle content, so mapping the same input
produces byte-identical Bundles. Clinical text is preserved verbatim: decoding
a DocumentReference attachment returns exactly the canonical record text. No
medical terminology codes (LOINC, SNOMED CT, ICD) are invented; a
source-provided diagnostic code is preserved as an Identifier in a clearly
project-owned namespace.

**Run the FHIR pipeline** (from `backend/`, virtual environment active) — this
runs ingestion, then mapping, validation, and persistence:

```bash
python -m app.fhir.cli ../data/synthetic --output-dir ../data/generated/fhir --database-url sqlite:///../data/generated/ehr_media.db
```

Exit codes: `0` all Bundles valid, `1` one or more Bundles invalid (reports
still written), `2` unrecoverable configuration/input/storage failure. No API
key or network access is required.

**Inspect exported Bundles.** Each patient Bundle is written to
`bundle_<patient_id>.json` (readable, sorted keys, LF newlines) alongside an
aggregate `fhir_report.json`. Both live under the git-ignored output directory.

**Validation layers.** Every Bundle passes through three independent layers,
recorded per patient in the report:

1. `fhir.resources` model validation (library-level structural/type checks).
2. Project reference-integrity validation (single Patient, unique IDs and
   `fullUrl`s, resolvable local references, complete and exclusive record
   coverage, matching resource types, valid attachment payloads, deterministic
   ordering).
3. A scoped **R4 compatibility guard** (see below).

A Bundle is valid only when it has no `error`-severity issues; warnings stay
visible but never mark a Bundle invalid. Broken references are reported, never
silently repaired.

**SQLite persistence.** Bundles and validation reports are stored in SQLite
(via SQLAlchemy 2) keyed on patient ID — one current Bundle and one current
report each. Persistence is idempotent: re-running with unchanged input reuses
rows (`unchanged`); a changed Bundle hash replaces the stored Bundle and
report (`updated`). Writes are transactional and roll back on failure. The
local database path is git-ignored.

### FHIR R4/R4B compatibility strategy

- **Target specification:** FHIR R4 4.0.1
- **Model library:** `fhir.resources`
- **Model namespace:** `R4B`
- **Compatibility strategy:** R4 field subset

The installed `fhir.resources` release exposes older compatible resources
through the `R4B` namespace. All `fhir.resources.R4B` imports are isolated
under `backend/app/fhir/`, and the mapper emits only fields shared with FHIR
R4 4.0.1 for the five resources used. The R4 compatibility guard enforces an
explicit allowlist of those fields and resource types and rejects any
R4B-only field, unexpected resource type, or profile/extension the mapper
should never emit.

This guard is **scoped to this project's output**; it is not a replacement for
the official HL7 FHIR Validator and does not implement the full specification.
The project does not claim official R4 conformance was tested.

**Optional:** to independently check exported Bundles against the official
validator, download the HL7 [FHIR Validator CLI](https://github.com/hapifhir/org.hl7.fhir.core/releases)
(a Java JAR; not vendored and not required for the Python test suite) and run,
for example:

```bash
# optional, requires Java and a separate download
java -jar validator_cli.jar data/generated/fhir/bundle_PAT-000123.json -version 4.0.1
```

## Clinical summarization

Stored valid FHIR Bundles are summarized into concise, structured clinical
summaries through the Anthropic API, with results cached in SQLite.

**Configure the Anthropic API.** Set two environment variables (see
`.env.example`):

- `ANTHROPIC_API_KEY` — required only to generate new summaries. Cached
  summaries are readable without a key.
- `ANTHROPIC_MODEL` — the model to use (configurable; e.g. `claude-sonnet-5`).

**Summary structure.** Each summary is a fixed Pydantic model: `patient_id`,
`chief_concern`, `key_diagnoses`, `recent_media_records`, `flagged_anomalies`,
`confidence` (`low` | `medium` | `high`), `disclaimer`, `source_resource_ids`,
and `word_count`. The complete rendered summary, including the disclaimer, is
kept **under 200 words** — enforced in application code, not trusted to the
model. A fixed, application-controlled disclaimer is always added and can never
be altered or omitted by the model. Absent evidence is reported as the explicit
phrase `Not documented`; diagnoses, anomalies, and dates are never invented.

**Prompt safety.** A versioned prompt (`clinical-summary-v1`) instructs the
model to use only facts present in the supplied records, avoid treatment
recommendations, never infer a diagnosis from an abnormal result, avoid
exaggerating certainty, cite only the supplied FHIR resource IDs, and return
only structured output. The prompt lives in a dedicated module for review and
versioning.

**Evidence extraction.** A deterministic layer converts a stored Bundle into a
compact prompt payload — decoded DocumentReference attachments, DiagnosticReport
conclusions, titles/codes, dates, and resource IDs — in stable order. The full
serialized Bundle and raw base64 payloads are never sent to the API.

**Caching.** The cache key is `(patient_id, record_hash, model, prompt_version)`,
where `record_hash` is the stored Bundle hash. A matching key returns the cached
summary without calling the provider (so no API key is needed); a changed Bundle
hash regenerates and stores a new row without overwriting historical entries.

**Automated quality checks.** Every summary is checked deterministically: all
required sections present, under the word limit, exact disclaimer, valid
confidence value, and every cited resource ID present in *this* patient's
Bundle (never another patient's). Results are recorded in a structured quality
report. These checks are **not** a substitute for clinician review.

**Run the summarization CLI** (from `backend/`, virtual environment active) —
it reads Bundles already stored by the FHIR pipeline and never re-runs
ingestion or FHIR normalization:

```bash
python -m app.summarization.cli \
    --database-url sqlite:///../data/generated/ehr_media.db \
    --output-dir ../data/generated/summaries
```

Add `--patient-id PAT-000123` to summarize one patient. The CLI writes
`summaries.json` and `summary_quality_report.json` (deterministic, git-ignored
output), prints generated/cached/skipped/failed counts, continues past
individual failures, and returns a nonzero exit code when any summary fails.

> Summaries are assistive artifacts generated by an AI system and require human
> review; they are not a clinical decision or a substitute for professional
> judgment.

## Frontend setup

Requires Node.js 22+.

```bash
cd frontend
npm install
npm run dev
```

The application shell serves at http://localhost:5173.

## Quality commands

Backend (from `backend/`, with the virtual environment active):

```bash
ruff check .           # lint
ruff format --check .  # formatting
mypy .                 # static types (strict)
pytest                 # tests
```

Frontend (from `frontend/`):

```bash
npm run lint       # ESLint
npm run typecheck  # TypeScript
npm run build      # production build
```

All of these run in CI on every push and pull request.

## Repository layout

```
backend/            FastAPI application and tests
frontend/           React + TypeScript + Vite + Tailwind interface
data/synthetic/     synthetic EHR fixtures (never real data)
docs/               product requirements and architecture
scripts/            development and data-generation utilities
.github/workflows/  CI pipelines
```
