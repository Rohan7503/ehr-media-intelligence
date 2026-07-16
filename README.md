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

**Ingestion phase complete.** The repository structure, backend API skeleton
(`GET /health`), frontend application shell, tooling, CI, and the full
ingestion and cleaning pipeline are in place. FHIR mapping, summarization,
embeddings, and search are documented in
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
