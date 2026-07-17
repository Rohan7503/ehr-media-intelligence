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

**End-to-end product complete.** The backend API (`GET /health`, `POST /search`,
`GET /patients/{id}`), the ingestion and cleaning pipeline, FHIR R4-compatible
mapping with Bundle validation and SQLite persistence, cached clinical
summarization via the Anthropic API, semantic search over FHIR resources and
summaries (sentence-transformers + ChromaDB), and the clinician-facing React +
Tailwind search interface with a patient detail drawer are all in place, along
with tooling and CI. Remaining work is incremental (authentication, real EHR
feeds, and other items are out of scope; see
[docs/product-requirements.md](docs/product-requirements.md)).

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

## Semantic search

Clinical resources and any available cached summaries are embedded with
sentence-transformers (`all-MiniLM-L6-v2`, configurable via `EMBEDDING_MODEL`)
and indexed in persistent ChromaDB (`CHROMA_PATH` / `CHROMA_COLLECTION`).

**What is indexed.** From every valid stored Bundle: each DocumentReference and
DiagnosticReport as readable text (decoded attachments and conclusions, never
serialized JSON or base64), plus each available cached clinical summary.
Summaries are included only when they have already been generated — the index
works fine with none. Chroma document IDs are deterministic, so re-indexing
unchanged data creates no duplicates, and when a patient's Bundle changes, stale
entries for that patient are removed.

**Scoring.** Cosine distance is converted to a relevance score
`1 - distance / 2` (higher is better). Each patient's best-matching summary adds
a small patient-level boost (`score = base + 0.1 * summary_relevance`); the
returned result is always the clinical resource, never the summary. Results are
clinical resources only, ordered by descending score then ascending resource ID,
limited to five.

**Build the index** (from `backend/`, virtual environment active) — reads
Bundles and summaries already stored; it never re-runs ingestion, FHIR mapping,
or summarization, and makes no Anthropic calls:

```bash
python -m app.search.cli \
    --database-url sqlite:///../data/generated/ehr_media.db \
    --chroma-path ../data/generated/chroma
```

The first run downloads the embedding model; it prints resource, summary,
inserted, updated, unchanged, and removed counts and exits nonzero on an
unrecoverable database or Chroma failure.

**Run the API:**

```bash
uvicorn app.main:app --reload
```

**`POST /search`** — body plus optional query-parameter filters:

```bash
curl -X POST 'http://127.0.0.1:8000/search?resource_type=DiagnosticReport&date_from=2024-01-01&date_to=2024-12-31' \
    -H 'Content-Type: application/json' \
    -d '{"query": "recent abnormal chest imaging"}'
```

Response:

```json
{
  "query": "recent abnormal chest imaging",
  "result_count": 5,
  "elapsed_ms": 18.3,
  "results": [
    {
      "patient_id": "PAT-000123",
      "patient_name": "Avery Kestrel",
      "mrn": "MRN-000123",
      "resource_id": "…",
      "resource_type": "DiagnosticReport",
      "record_date": "2024-05-01",
      "title": "Chest X-ray report",
      "relevance_score": 0.72,
      "resource_text_snippet": "Chest X-ray report …",
      "clinical_summary_snippet": null
    }
  ]
}
```

**Filtering.** Optional `resource_type` (`DocumentReference` or
`DiagnosticReport`), `date_from`, and `date_to`. Undated resources are excluded
whenever a date filter is supplied. Invalid requests (empty query,
`date_from > date_to`, unsupported `resource_type`, malformed dates) return
`422`; an unavailable or empty index returns `503`. The embedding model and
Chroma client are loaded lazily and reused across requests, never at import
time.

**Warm performance benchmark.** With the index built, time a warm search (model
and Chroma already loaded) over the checked-in dataset:

```bash
python - <<'PY'
import time
from app.search.embeddings import SentenceTransformerEmbedder
from app.search.index_store import open_persistent_index
from app.search.service import SearchService, SearchQuery
emb = SentenceTransformerEmbedder("all-MiniLM-L6-v2")
idx = open_persistent_index(path="../data/generated/chroma", collection="ehr_media", embedder=emb)
svc = SearchService(index=idx, embedder=emb)
svc.search(SearchQuery(query="warm up"))  # warm the model and client
start = time.perf_counter()
svc.search(SearchQuery(query="recent abnormal chest imaging"))
print(f"warm search: {(time.perf_counter() - start) * 1000:.1f} ms over {idx.count()} docs")
PY
```

The target is under two seconds for at least 50 clinical records; warm searches
over the 58-record dataset run in tens of milliseconds.

## Frontend — clinician search interface

A React + TypeScript + Tailwind CSS single page that talks to the backend with
the native Fetch API (no Axios, no global state library).

**Prerequisites.** Run the backend and build the Chroma index first (above), so
`POST /search` and `GET /patients/{id}` return data.

**Run it** (requires Node.js 22+):

```bash
cd frontend
npm install
npm run dev
```

The app serves at http://localhost:5173.

**`VITE_API_BASE_URL`.** The backend base URL is read from this build-time
variable (see `.env.example`); it defaults to `http://127.0.0.1:8000`. Point it
at your backend if it runs elsewhere, e.g.:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

**Search and filters.** Enter a natural-language query and press Enter or the
Search button. Filter by resource type (all / DocumentReference /
DiagnosticReport) and by a from/to date range; **Clear filters** resets them.
Filters are preserved across searches, empty queries are not submitted, and
duplicate submissions are blocked while a search is in flight. Backend
validation and service errors are shown as readable messages, never raw
responses. Results are the top five ranked resource cards, each showing the
patient, MRN, record date (or “Date unavailable”), a resource-type badge, the
relevance as a percentage, the title, a text snippet, and a cached-summary
snippet when one exists.

**Patient detail.** Selecting a result card (click, Enter, or Space) opens a
patient detail panel — a right-side drawer on desktop, a full-screen panel on
small screens. It shows demographics, the Bundle validation status, the full
cached clinical summary with a confidence indicator and the fixed AI disclaimer
(or a clear message when no summary is cached — **summaries appear only when
they have already been generated**), and the linked FHIR resources as readable
text (long text collapses with a Show more / Show less toggle). Raw FHIR JSON and
base64 are never displayed.

**Accessibility.** Every control has a visible or ARIA label; result cards are
keyboard operable with visible focus rings; search status is announced through a
polite live region; the drawer uses `role="dialog"` with `aria-modal`, traps
focus, closes on Escape or backdrop click, restores focus to the originating
card, and locks background scroll; meaning never relies on color alone; and
animations respect `prefers-reduced-motion`.

**States.** The interface has explicit initial, loading, results, no-results, and
error states for search, and loading, not-found, error, and summary-unavailable
states for patient detail.

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
