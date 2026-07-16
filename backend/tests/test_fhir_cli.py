"""End-to-end tests for the FHIR CLI and full ingestion→FHIR→SQLite flow."""

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

import app.fhir.pipeline as pipeline_module
from app.domain.patient import Patient
from app.domain.record import ClinicalRecord
from app.fhir.cli import EXIT_FATAL, EXIT_INVALID, EXIT_OK, main
from app.persistence.database import create_db_engine
from app.persistence.repositories.bundles import BundleRepository

SYNTHETIC_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"

_VALID_JSON = [
    {
        "patient_id": "SRC-1",
        "mrn": "123",
        "given_name": "Avery",
        "family_name": "Kestrel",
        "dob": "1984-03-02",
        "gender": "F",
        "record_id": "R-1",
        "record_type": "note",
        "record_date": "2024-05-01",
        "title": "Visit note",
        "text": "Stable on current therapy.",
    }
]


def _db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'ehr.db'}"


def _write_input(tmp_path: Path) -> Path:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.json").write_text(json.dumps(_VALID_JSON), encoding="utf-8")
    return inputs


def test_cli_success_path(tmp_path: Path) -> None:
    inputs = _write_input(tmp_path)
    out = tmp_path / "out"
    exit_code = main([str(inputs), "--output-dir", str(out), "--database-url", _db_url(tmp_path)])
    assert exit_code == EXIT_OK
    report = json.loads((out / "fhir_report.json").read_text(encoding="utf-8"))
    assert report["bundle_count"] == 1
    assert report["valid_bundle_count"] == 1
    assert (out / "bundle_PAT-000123.json").exists()


def test_cli_fatal_on_missing_input(tmp_path: Path) -> None:
    exit_code = main(
        [
            str(tmp_path / "missing"),
            "--output-dir",
            str(tmp_path / "o"),
            "--database-url",
            _db_url(tmp_path),
        ]
    )
    assert exit_code == EXIT_FATAL


def test_cli_invalid_bundle_exit_still_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _write_input(tmp_path)
    out = tmp_path / "out"
    from fhir.resources.R4B.patient import Patient as FHIRPatient

    def boom(patient: Patient, records: list[ClinicalRecord]) -> object:
        FHIRPatient(birthDate="not-a-date")  # raises a real ValidationError
        raise AssertionError("unreachable")

    monkeypatch.setattr(pipeline_module, "map_patient_bundle", boom)
    exit_code = main([str(inputs), "--output-dir", str(out), "--database-url", _db_url(tmp_path)])
    assert exit_code == EXIT_INVALID
    # The aggregate report is still written despite the invalid Bundle.
    report = json.loads((out / "fhir_report.json").read_text(encoding="utf-8"))
    assert report["invalid_bundle_count"] == 1


def test_exported_json_is_byte_identical_across_runs(tmp_path: Path) -> None:
    inputs = _write_input(tmp_path)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    assert main([str(inputs), "--output-dir", str(out1), "--database-url", _db_url(tmp_path)]) == 0
    assert (
        main(
            [
                str(inputs),
                "--output-dir",
                str(out2),
                "--database-url",
                f"sqlite:///{tmp_path / 'other.db'}",
            ]
        )
        == 0
    )
    bundle = "bundle_PAT-000123.json"
    assert (out1 / bundle).read_bytes() == (out2 / bundle).read_bytes()


def test_full_synthetic_dataset_end_to_end(tmp_path: Path) -> None:
    assert SYNTHETIC_DIR.exists(), "checked-in synthetic dataset is missing"
    out = tmp_path / "fhir"
    db_url = _db_url(tmp_path)

    exit_code = main([str(SYNTHETIC_DIR), "--output-dir", str(out), "--database-url", db_url])
    assert exit_code == EXIT_OK

    report = json.loads((out / "fhir_report.json").read_text(encoding="utf-8"))
    assert report["patient_count"] == 10
    assert report["bundle_count"] == 10
    assert report["valid_bundle_count"] == 10
    assert report["invalid_bundle_count"] == 0
    assert report["resource_totals"]["Patient"] == 10
    # 58 accepted clinical records -> 58 clinical resources, none from
    # duplicates/rejections/conflicts.
    clinical_total = (
        report["resource_totals"]["DocumentReference"]
        + report["resource_totals"]["DiagnosticReport"]
    )
    assert clinical_total == 58
    assert all(v["valid"] for v in report["validations"])
    assert all(issue["severity"] != "error" for v in report["validations"] for issue in v["issues"])

    # Every clinical resource appears exactly once across all exported bundles.
    bundle_files = sorted(out.glob("bundle_PAT-*.json"))
    assert len(bundle_files) == 10
    clinical_ids: list[str] = []
    for path in bundle_files:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        for entry in bundle["entry"]:
            if entry["resource"]["resourceType"] in ("DocumentReference", "DiagnosticReport"):
                clinical_ids.append(entry["resource"]["id"])
    assert len(clinical_ids) == 58
    assert len(set(clinical_ids)) == 58

    # SQLite holds exactly one current Bundle and report per patient.
    engine = create_db_engine(db_url)
    with Session(engine) as session:
        repo = BundleRepository(session)
        assert repo.count_bundles() == 10
        assert repo.count_reports() == 10
    engine.dispose()

    # Re-running adds no duplicate rows and re-exports byte-identically.
    out2 = tmp_path / "fhir2"
    assert main([str(SYNTHETIC_DIR), "--output-dir", str(out2), "--database-url", db_url]) == 0
    engine = create_db_engine(db_url)
    with Session(engine) as session:
        assert BundleRepository(session).count_bundles() == 10
    engine.dispose()
    for path in bundle_files:
        assert path.read_bytes() == (out2 / path.name).read_bytes()
