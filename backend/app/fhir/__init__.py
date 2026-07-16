"""FHIR R4-compatible mapping, validation, and bundling.

All imports of ``fhir.resources.R4B`` are isolated within this package. The
rest of the application depends only on the plain data structures and report
models exposed here, never on the FHIR model library directly.

Target specification: FHIR R4 4.0.1
Model library:        fhir.resources
Model namespace:      R4B (Pydantic v2-compatible; R4B is a superset of R4 for
                      the resources used here)
Compatibility:        R4 field subset (see ``app.fhir.compatibility``)
"""
