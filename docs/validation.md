# Validation

This document records **offline developer validation** of the EHR Media
Intelligence platform against the checked-in synthetic dataset. It is developer
evidence review, **not clinical validation**. All data is synthetic.

No live Anthropic or OpenAI API calls were made during this validation.

## Ingestion and FHIR pipeline

Run from `backend/` against `data/synthetic/`, writing to the git-ignored
`data/generated/`:

```bash
python -m app.ingestion.cli ../data/synthetic --output-dir ../data/generated
python -m app.fhir.cli ../data/synthetic \
    --output-dir ../data/generated/fhir \
    --database-url sqlite:///../data/generated/ehr_media.db
```

| Check | Expected | Observed |
| --- | --- | --- |
| Raw records ingested | 66 | 66 |
| Accepted clinical records | 58 | 58 |
| Duplicates / rejected / conflicts | reported | 3 / 3 / 2 |
| Valid patient Bundles | 10 | 10 (10/10 valid) |
| Clinical resources (DocumentReference + DiagnosticReport) | 58 | 33 + 25 = 58 |
| Each accepted record represented exactly once | yes | 58 unique clinical resource IDs across 10 bundles |
| Every Bundle has exactly one Patient | yes | verified |

## Semantic search index

```bash
python -m app.search.cli \
    --database-url sqlite:///../data/generated/ehr_media.db \
    --chroma-path ../data/generated/chroma
```

| Check | Expected | Observed |
| --- | --- | --- |
| Indexed clinical resources | 58 | 58 |
| Indexed summaries | 0+ (depends on cache) | 0 (no cached summaries present) |
| Fresh build | inserts all | 58 inserted, 0 updated, 0 unchanged, 0 removed |
| Idempotent re-index | no rewrites | 0 inserted, 0 updated, 58 unchanged, 0 removed |

Summaries are indexed only when they already exist in the cache; with no cached
summaries the index contains the 58 clinical resources alone, as expected.

## Warm search benchmarks

Warm searches (embedding model and Chroma client already loaded) over the
58-resource index. Target: under two seconds for at least 50 clinical records.

| Query | Latency | Top result |
| --- | --- | --- |
| recent abnormal chest imaging | ~20 ms | DiagnosticReport — Chest X-ray report |
| fasting lipid panel cholesterol results | ~20 ms | DiagnosticReport — Lipid panel |
| hypertension medication follow up | ~20 ms | DocumentReference — Medication review |
| complete blood count laboratory report | ~19 ms | DiagnosticReport — Complete blood count |
| telehealth check in visit note | ~20 ms | DocumentReference — Telehealth check-in |
| comprehensive metabolic panel monitoring | ~18 ms | DiagnosticReport — Comprehensive metabolic panel |

All queries completed in tens of milliseconds — well under the two-second
target — and returned the semantically correct clinical resource first.

## Summarization

**The Anthropic provider integration was validated using mocked provider
responses. A live API request was not performed because trial API credits were
not available.**

The summarization implementation includes:

- **Real Anthropic SDK integration** — `AnthropicSummaryProvider` uses the
  installed `anthropic` SDK's Messages API.
- **Structured tool-call output** — a forced tool call returns the summary as a
  validated JSON object.
- **Required summary sections** — chief concern, key diagnoses, recent
  imaging/lab/media records, flagged anomalies, confidence, and source resource
  IDs.
- **Under-200-word enforcement** — the rendered summary is measured in
  application code and rejected if it reaches 200 words; not trusted to the
  model.
- **Fixed non-clinical disclaimer** — an application-controlled disclaimer is
  always injected; the model cannot alter or omit it (the model's draft schema
  has no disclaimer field).
- **Confidence field** — a `low` / `medium` / `high` enum.
- **Source-resource ID validation** — every cited ID must exist in that
  patient's Bundle; cited IDs from another patient fail quality validation.
- **SQLite caching** keyed by patient, Bundle hash, model, and prompt version;
  historical entries are preserved.
- **Provider error handling** — authentication, rate-limit, service, and
  malformed-response failures become typed application errors; at most one
  retry for a transient connection/timeout error.
- **Cache-hit behavior that avoids provider calls** — a cache hit returns the
  stored summary without constructing the client or requiring an API key.

These behaviors are exercised by the automated test suite using a **fake
provider** (`tests/test_summarization_*`), which makes no network calls and
needs no API key.

### Representative evidence review (developer, not clinical)

Three synthetic patients were reviewed by comparing their source FHIR evidence
to a deterministic, evidence-grounded summary (authored from the records and
validated through the same assembly and quality checks the production pipeline
uses). Each patient's records describe routine follow-up with normal / stable
findings, so a faithful summary must report no anomalies rather than invent
them.

| Patient | Condition | Sections | Factual consistency | Unsupported claims | Anomaly preservation | Words | Disclaimer | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PAT-000123 (Avery Kestrel) | hypertension | 5/5 | grounded in records | none | none documented → "Not documented" | 52 | present | PASS |
| PAT-AB123 (Imani Solano) | asthma | 5/5 | grounded in records | none | none documented → "Not documented" | 52 | present | PASS |
| PAT-000456 (Rowan Falk) | type 2 diabetes | 5/5 | grounded in records | none | none documented → "Not documented" | 56 | present | PASS |

For all three: every required section was present, the content matched the
source evidence (chief concern from the follow-up note, diagnosis from the
documented condition, recent media records from the dated diagnostic reports),
no unsupported diagnoses or interpretations were introduced, the absence of
abnormal findings was correctly represented as "Not documented" rather than
fabricated, the rendered summary stayed well under 200 words, the fixed
disclaimer was present, and every cited source resource ID resolved to that
patient's Bundle.

This is developer validation of the summarization mechanics and evidence
grounding. It is **not** clinical validation and does not constitute clinical
review.

## Browser behavior

A manual browser smoke test was performed against the running frontend and
backend. In that session:

- different search queries returned different ranked top-five results;
- resource-type filtering returned only the selected type;
- date filtering restricted results to the chosen range;
- selecting a result card opened the patient detail drawer;
- linked FHIR resources displayed as readable text (no raw JSON or base64);
- pressing Escape closed the drawer;
- the missing-summary state rendered correctly when no cached summary existed;
- the layout was usable in the tested browser, including at a narrow width.

This was a manual smoke test in a single browser, not automated browser testing,
exhaustive accessibility validation, or clinician validation. The underlying
backend HTTP contracts were also checked directly, and `npm run lint`,
`npm run typecheck`, and `npm run build` pass.

## Limitations

- No live provider call was made (trial API credits unavailable); summarization
  is validated with a fake provider.
- With no cached summaries present, the search index and patient detail views
  correctly show the no-summary state; generating real summaries requires an
  `ANTHROPIC_API_KEY`.
- All validation used synthetic data only. This platform is a demonstration and
  is not for clinical use.
