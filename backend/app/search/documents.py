"""Build deterministic index documents from Bundles and cached summaries.

Each clinical resource (DocumentReference, DiagnosticReport) and each available
cached summary becomes one :class:`IndexDocument` with readable text (never
serialized JSON or raw base64), stable metadata, and a deterministic ID. A
content hash over the text and metadata lets the indexer skip unchanged
documents so re-indexing is idempotent and cheap.
"""

import hashlib
import json
from dataclasses import dataclass, field

from app.summarization.cache_models import SummaryCacheRow
from app.summarization.evidence import extract_patient_evidence

#: Chroma metadata document-kind discriminators.
KIND_RESOURCE = "resource"
KIND_SUMMARY = "summary"

_SNIPPET_MAX = 400


@dataclass
class IndexDocument:
    """One document to embed and store in the vector index."""

    doc_id: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)

    def with_content_hash(self) -> dict[str, str]:
        """Return metadata plus a content hash over text and metadata."""
        base = dict(self.metadata)
        payload = json.dumps(
            {"text": self.text, "metadata": base}, sort_keys=True, ensure_ascii=False
        )
        base["content_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return base


def _patient_identity(bundle: dict[str, object]) -> tuple[str, str]:
    """Extract ``(patient_name, mrn)`` from the Bundle's Patient resource."""
    entries = bundle.get("entry")
    if not isinstance(entries, list):
        return "", ""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        resource = entry.get("resource")
        if not isinstance(resource, dict) or resource.get("resourceType") != "Patient":
            continue
        name = ""
        names = resource.get("name")
        if isinstance(names, list) and names and isinstance(names[0], dict):
            given = names[0].get("given")
            family = names[0].get("family")
            parts: list[str] = []
            if isinstance(given, list):
                parts.extend(str(g) for g in given)
            if isinstance(family, str):
                parts.append(family)
            name = " ".join(parts)
        mrn = ""
        identifiers = resource.get("identifier")
        if isinstance(identifiers, list) and identifiers and isinstance(identifiers[0], dict):
            value = identifiers[0].get("value")
            if isinstance(value, str):
                mrn = value
        return name, mrn
    return "", ""


def resource_id_for_doc(resource_id: str) -> str:
    """Deterministic Chroma document ID for a clinical resource."""
    return f"resource:{resource_id}"


def summary_id_for_doc(row: SummaryCacheRow) -> str:
    """Deterministic Chroma document ID for a cached summary."""
    return f"summary:{row.patient_id}:{row.record_hash}:{row.model_name}:{row.prompt_version}"


def build_resource_documents(
    patient_id: str, bundle_hash: str, bundle_json: str
) -> list[IndexDocument]:
    """Build one index document per clinical resource in a Bundle."""
    bundle = json.loads(bundle_json)
    patient_name, mrn = _patient_identity(bundle)
    evidence = extract_patient_evidence(patient_id, bundle_json)

    documents: list[IndexDocument] = []
    for record in evidence.records:
        title = record.title or record.resource_type
        text = f"{title}\n{record.text}".strip()
        metadata: dict[str, str] = {
            "document_kind": KIND_RESOURCE,
            "patient_id": patient_id,
            "patient_name": patient_name,
            "mrn": mrn,
            "resource_id": record.resource_id,
            "resource_type": record.resource_type,
            "title": title,
            "bundle_hash": bundle_hash,
        }
        if record.date:
            metadata["record_date"] = record.date
        documents.append(
            IndexDocument(
                doc_id=resource_id_for_doc(record.resource_id), text=text, metadata=metadata
            )
        )
    return documents


def build_summary_documents(rows: list[SummaryCacheRow]) -> list[IndexDocument]:
    """Build one index document per available cached summary."""
    documents: list[IndexDocument] = []
    for row in rows:
        metadata = {
            "document_kind": KIND_SUMMARY,
            "patient_id": row.patient_id,
            "bundle_hash": row.record_hash,
            "model_name": row.model_name,
            "prompt_version": row.prompt_version,
        }
        documents.append(
            IndexDocument(doc_id=summary_id_for_doc(row), text=row.rendered_text, metadata=metadata)
        )
    return documents


def snippet(text: str) -> str:
    """A short, single-spaced snippet of a document for API responses."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_MAX:
        return collapsed
    return collapsed[:_SNIPPET_MAX].rstrip() + "…"
