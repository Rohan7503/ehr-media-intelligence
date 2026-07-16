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

Only `api` and `core` exist in the current scaffold; the rest are created when
their features are implemented. External services (Anthropic client, ChromaDB
client, embedding model, database sessions) are always injected as
dependencies so tests can substitute fakes.

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
