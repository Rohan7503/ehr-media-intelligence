"""Cached clinical summarization of stored FHIR Bundles via the Anthropic API.

Summaries are generated only from evidence extracted from valid stored
Bundles, constrained by a versioned safety prompt, validated against a fixed
Pydantic schema, kept under a hard word limit with an application-controlled
disclaimer, and cached in SQLite keyed on the Bundle hash, model, and prompt
version. Summaries are assistive only and are not a substitute for clinician
review.
"""
