"""Tests for the /health endpoint."""

from fastapi.testclient import TestClient

from app import __version__
from app.main import create_app


def test_health_returns_structured_response() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "EHR Media Intelligence"
    assert body["version"] == __version__
    assert isinstance(body["environment"], str)
