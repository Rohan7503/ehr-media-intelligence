"""Semantic search over stored FHIR resources and cached clinical summaries.

Clinical resource text and available cached summaries are embedded with
sentence-transformers and indexed in persistent ChromaDB. Search returns the
top clinical-resource matches, using summary similarity only as a small
patient-level relevance boost. Nothing here loads the embedding model or opens
Chroma at import time.
"""
