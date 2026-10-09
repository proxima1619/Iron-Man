"""Reference viewing must not masquerade as a measured or newly executed run."""
import hashlib
import os
from pathlib import Path

import pytest

from backend import main
from backend.contracts import TEPVariable
from backend.simulator.tep import reference
from tests.test_gateway import client, OP


@pytest.fixture
def reference_data(tmp_path, monkeypatch):
    # Small synthetic arrays test the parser/HTTP contract, not process physics.
    rows = [[sample * 1000 + column for column in range(52)] for sample in range(2)]
    data = {}
    for name, transpose in [("d00.dat", True), ("d01_te.dat", False)]:
        stored = list(zip(*rows)) if transpose else rows
        raw = ("\n".join(" ".join(map(str, row)) for row in stored) + "\n").encode()
        (tmp_path / name).write_bytes(raw)
        data[name] = {
            "condition": "normal" if transpose else "fault", "fault_index": None if transpose else 1,
            "split": "training" if transpose else "test", "observation_count": 2,
            "stored_layout": "variables_by_observations" if transpose else "observations_by_variables",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    (tmp_path / "readme.txt").write_bytes(b"Synthetic metadata for tests only")
    lock = {
        "column_order": [f"XMEAS{i}" for i in range(1, 42)] + [f"XMV{i}" for i in range(1, 12)],
        "source_files_sha256": {"readme.txt": hashlib.sha256((tmp_path / "readme.txt").read_bytes()).hexdigest()},
        "files": data,
    }
    monkeypatch.setattr(reference, "profile", lambda: lock)
    monkeypatch.setenv("IRON_MAN_TEP_REFERENCE_DIR", str(tmp_path))
    return tmp_path, lock


def test_transpose_and_column_mapping_are_preserved(reference_data):
    root, _ = reference_data
    original = (root / "d00.dat").read_bytes()
    for key, expected_column, unit in [("XMEAS7", 6, "kPa_gauge"), ("XMEAS9", 8, "degC"),
                                      ("XMV10", 50, "percent_full_scale"), ("XMV11", 51, "percent_full_scale")]:
        result = reference.series("d00.dat", key)
        assert result.values == [expected_column, 1000 + expected_column]
        assert result.sample_indices == [0, 1]
        assert result.definition.column_index == expected_column and result.definition.unit == unit
        assert result.statistics.mean == 500 + expected_column
        assert result.metadata.sample_period_s is None and result.metadata.random_seed is None
        assert result.metadata.data_origin == "simulation" and not result.metadata.used_for_approval
    assert (root / "d00.dat").read_bytes() == original


def test_fault_file_is_not_a_new_execution_or_confirmed_fault_onset(reference_data):
    result = reference.series("d01_te.dat", "XMEAS9")
    assert result.values == [8, 1008]
    assert result.file.fault_index == 1
    assert result.metadata.record_kind == "prerecorded_reference"
    assert result.metadata.fault_onset_sample is None
    assert result.metadata.comparison_status == "not_matched_to_current_open_loop_run"
    assert "baseline" not in result.model_dump() and "candidate" not in result.model_dump()


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "missing"])
def test_bad_values_never_return_partial_series(reference_data, value):
    root, lock = reference_data
    path = root / "d01_te.dat"
    raw = path.read_bytes().replace(b"1008", value.encode())
    path.write_bytes(raw)
    lock["files"][path.name]["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(reference.ReferenceFailure) as exc:
        reference.series(path.name, "XMV10")  # Also validate non-selected columns.
    assert exc.value.code == "INVALID_REFERENCE"


def test_truncated_or_unknown_layout_rejected():
    with pytest.raises(reference.ReferenceFailure): reference.parse_rows(b"1 2\n3 4", 2, "observations_by_variables")
    with pytest.raises(reference.ReferenceFailure): reference.parse_rows(b"1 2", 2, "unknown")


@pytest.mark.parametrize("target", ["d00.dat", "readme.txt"])
def test_changed_data_or_definition_is_rejected(reference_data, target):
    root, _ = reference_data
    (root / target).write_bytes(b"changed")
    with pytest.raises(reference.ReferenceFailure) as exc:
        reference.series("d00.dat", "XMEAS9")
    assert exc.value.code == "REFERENCE_PROFILE_MISMATCH"


def test_missing_source_or_data_never_uses_fixture(reference_data):
    root, _ = reference_data
    (root / "d00.dat").unlink()
    assert reference.catalog().files[0].present is False
    with pytest.raises(reference.ReferenceFailure): reference.series("d00.dat", "XMEAS9")
    (root / "readme.txt").unlink()
    with pytest.raises(reference.ReferenceFailure): reference.catalog()


@pytest.mark.parametrize("file_id,variable,code", [("../readme.txt", "XMEAS9", "UNKNOWN_REFERENCE_FILE"),
    ("d99.dat", "XMEAS9", "UNKNOWN_REFERENCE_FILE"), ("d00.dat", "XMV12", "UNKNOWN_REFERENCE_VARIABLE"),
    ("d00.dat", "temperature_c", "UNKNOWN_REFERENCE_VARIABLE")])
def test_unsupported_names_rejected(reference_data, file_id, variable, code):
    with pytest.raises(reference.ReferenceFailure) as exc: reference.series(file_id, variable)
    assert exc.value.code == code


def test_unknown_units_rejected(reference_data, monkeypatch):
    monkeypatch.setitem(reference.VARIABLES, "XMEAS9", TEPVariable.model_construct(name="Temperature", unit="unknown"))
    with pytest.raises(reference.ReferenceFailure) as exc: reference.series("d00.dat", "XMEAS9")
    assert exc.value.code == "UNKNOWN_REFERENCE_UNITS"


def test_reference_api_auth_error_and_no_gateway_effect(client, reference_data):
    root, _ = reference_data
    before = main.gateway.adapter.read_state().model_dump()
    assert client.get("/tep/reference/catalog").status_code == 401
    catalog = client.get("/tep/reference/catalog", headers=OP)
    assert catalog.status_code == 200 and len(catalog.json()["variables"]) == 52
    response = client.get("/tep/reference/series/d00.dat?variable=XMV10", headers=OP)
    assert response.status_code == 200
    assert response.json()["values"] == [50., 1050.]
    assert response.json()["metadata"]["used_for_approval"] is False
    (root / "d00.dat").write_bytes(b"corrupt")
    error = client.get("/tep/reference/series/d00.dat", headers=OP)
    assert error.status_code == 503 and error.json()["code"] == "REFERENCE_PROFILE_MISMATCH"
    assert "values" not in error.json()
    assert client.get("/tep/reference/series/d00.dat?variable=XMV12", headers=OP).status_code == 422
    assert client.get("/tep/reference/series/d99.dat", headers=OP).status_code == 404
    assert main.gateway.adapter.read_state().model_dump() == before
    assert main.gateway.list_records() == []


@pytest.mark.skipif(os.getenv("IRON_MAN_TEST_TEP_REFERENCE") != "1", reason="Opt in after supplying the pinned local dataset")
def test_all_uploaded_files_are_readable_and_identical_on_repeat():
    catalog = reference.catalog()
    assert len(catalog.files) == 44
    assert sum(file.observation_count for file in catalog.files) == 31700
    for file in catalog.files:
        result = reference.series(file.file_id, "XMEAS9")  # Parser validates all 52 variables.
        assert len(result.values) == file.observation_count
        assert result == reference.series(file.file_id, "XMEAS9")
    normal = reference.series("d00.dat", "XMV10")
    assert normal.statistics.minimum == 39.51 and normal.statistics.maximum == 42.641
    assert normal.statistics.mean == pytest.approx(41.09475)
