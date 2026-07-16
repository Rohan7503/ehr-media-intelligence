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

**Scaffold phase.** The repository structure, backend API skeleton
(`GET /health`), frontend application shell, tooling, and CI are in place.
Ingestion, FHIR mapping, summarization, embeddings, and search are documented
in [docs/product-requirements.md](docs/product-requirements.md) but not yet
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
