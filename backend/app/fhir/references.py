"""Internal Bundle reference construction.

References between resources in a ``collection`` Bundle are literal
``urn:uuid:<id>`` references that must exactly match the target entry's
``fullUrl``. These helpers build those references from a resource ID so the
mapper and the reference-integrity validator agree on the exact string form.
"""

from fhir.resources.R4B.reference import Reference

from app.fhir.identifiers import full_url


def reference_to(resource_id: str) -> Reference:
    """A Reference whose literal value is the target's ``urn:uuid:`` fullUrl."""
    return Reference(reference=full_url(resource_id))
