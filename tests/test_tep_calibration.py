import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from backend.contracts import TEPCommand, TEPResult
from backend.simulator.tep import calibration as cal, service as tep
from scripts.generate_tep_calibration_example import example


@pytest.fixture(scope="module")
def fitted():
    return cal.fit(example())


def test_simulated_response_recovery_and_no_runtime_activation(fitted):
    for variable, truth in [("XMV10", 12.), ("XMV11", 8.)]:
        parameter = fitted.fitted_parameters[variable]
        assert parameter.tau_s == pytest.approx(truth, abs=1e-5)
        assert parameter.validation_passed
        assert parameter.validation_errors.rmse < .001
        assert parameter.default_validation_errors.rmse > parameter.validation_errors.rmse
    assert fitted.status == "candidate_ready" and fitted.data_origin == "simulation"
    assert not fitted.activated and not fitted.can_approve
    assert fitted.whole_process_field_validation == "not_performed"
    assert tep.MODEL_VERSION == "nist-tep-81a7ac9-ironman-v1"
    with pytest.raises(ValidationError): TEPResult.model_validate(fitted.model_dump())


def test_validation_never_changes_fitted_coefficients(fitted):
    data = example().model_dump(mode="json")
    for run in data["validation"]:
        for sample in run["samples"]:
            sample["actual_percent_full_scale"] += 8
    rejected = cal.fit(cal.TEPActuatorCalibrationDataset.model_validate(data))
    assert rejected.status == "candidate_rejected"
    for variable in ("XMV10", "XMV11"):
        assert rejected.fitted_parameters[variable].tau_s == fitted.fitted_parameters[variable].tau_s
        assert "VALIDATION_ERROR_EXCEEDED" in rejected.fitted_parameters[variable].rejection_reasons
    assert not rejected.activated and not rejected.can_approve


@pytest.mark.parametrize("problem", ["duplicate_id", "duplicate_source", "duplicate_samples", "overlap",
    "timezone", "wrong_unit", "target_as_feedback", "nonfinite", "missing_feedback", "bad_quality",
    "out_of_range", "unsupported_parameter", "same_version", "missing_validation_channel", "bad_time_grid"])
def test_bad_or_leaking_input_rejected(problem):
    data = example().model_dump(mode="json")
    run, train = data["validation"][0], data["training"][0]
    if problem == "duplicate_id": run["recording_id"] = train["recording_id"]
    elif problem == "duplicate_source": run["source_recording_id"] = train["source_recording_id"]
    elif problem == "duplicate_samples": run["samples"] = train["samples"]
    elif problem == "overlap": run["started_at"] = train["started_at"]
    elif problem == "timezone": run["started_at"] = "2026-10-09T00:00:00"
    elif problem == "wrong_unit": data["channels"]["XMV10"]["unit"] = "rpm"
    elif problem == "target_as_feedback": data["channels"]["XMV10"]["actual_tag"] = "XMV10"
    elif problem == "nonfinite": run["samples"][1]["actual_percent_full_scale"] = float("nan")
    elif problem == "missing_feedback": del run["samples"][1]["actual_percent_full_scale"]
    elif problem == "bad_quality": run["samples"][1]["quality"] = "suspect"
    elif problem == "out_of_range": run["samples"][1]["actual_percent_full_scale"] = 101
    elif problem == "unsupported_parameter": data["channels"]["XMV10"]["cooling_efficiency"] = .65
    elif problem == "same_version": data["candidate_model_version"] = tep.MODEL_VERSION
    elif problem == "missing_validation_channel": data["validation"].pop()
    elif problem == "bad_time_grid": run["samples"][1]["time_s"] = 1.01
    with pytest.raises(ValidationError): cal.TEPActuatorCalibrationDataset.model_validate(data)


def test_unexcited_measurements_cannot_identify_response_time():
    data = example().model_dump(mode="json")
    for run in data["training"]:
        for point in run["samples"]:
            point.update(target_percent_full_scale=40., actual_percent_full_scale=40.)
    # Preserve different trace lengths so this test reaches the excitation check.
    data["training"][1]["samples"].pop()
    with pytest.raises(ValueError, match="observable actuator transient"):
        cal.fit(cal.TEPActuatorCalibrationDataset.model_validate(data))


def test_search_boundary_is_rejected():
    data = example().model_dump(mode="json")
    data["channels"]["XMV10"]["maximum_tau_s"] = 6.
    result = cal.fit(cal.TEPActuatorCalibrationDataset.model_validate(data))
    assert result.status == "candidate_rejected"
    assert "FIT_AT_SEARCH_BOUNDARY" in result.fitted_parameters["XMV10"].rejection_reasons


def test_insufficient_sampling_resolution_is_rejected():
    data = example().model_dump(mode="json")
    for split in ("training", "validation"):
        for run in data[split]:
            run["samples"] = [run["samples"][i] for i in (0, 58, 59, 120)]
    for channel in data["channels"].values():
        channel["actual_resolution"] = .1
    result = cal.fit(cal.TEPActuatorCalibrationDataset.model_validate(data))
    assert result.status == "candidate_rejected"
    assert any("WEAK_PARAMETER_SENSITIVITY" in value.rejection_reasons for value in result.fitted_parameters.values())


def test_repeat_result_identity_and_input_hash(fitted):
    again = cal.fit(example())
    assert fitted.model_dump() == again.model_dump()
    assert len(fitted.canonical_dataset_sha256) == 64
    assert fitted.provenance["source_commit"] == "81a7ac9dc04f91bc0898c36f8522372e0e437fc1"


def test_cli_success_and_failure_preserve_original(tmp_path):
    source, output = tmp_path / "input.json", tmp_path / "candidate.json"
    original = example().model_dump_json(indent=2).encode()
    source.write_bytes(original)
    command = [sys.executable, "-m", "scripts.calibrate_tep", "--input", str(source), "--output", str(output)]
    first = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert first.returncode == 0, first.stderr
    result = cal.TEPActuatorCalibrationResult.model_validate_json(output.read_bytes())
    assert result.input_file_sha256 and not result.activated
    assert source.read_bytes() == original
    source.write_bytes(b"{not-json")
    failed = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert failed.returncode == 2
    error = cal.TEPActuatorCalibrationResult.model_validate_json(output.read_bytes())
    assert error.status == "failed" and not error.fitted_parameters
    assert source.read_bytes() == b"{not-json"
    assert subprocess.run(command[:-1] + [str(source)], capture_output=True, timeout=20).returncode == 2
    assert source.read_bytes() == b"{not-json"


@pytest.mark.skipif(os.getenv("IRON_MAN_TEST_TEP") != "1", reason="Requires the built external TE core")
@pytest.mark.parametrize("variable,value", [("XMV10", 42.), ("XMV11", 19.)])
def test_actuator_predictions_match_actual_external_core(variable, value):
    command = TEPCommand(type="set_tep_cooling_water", variable=variable, value=value, duration_s=30, sample_period_s=1)
    result = tep.simulate(command)
    assert result.status == "completed", result.detail
    index = 0 if variable == "XMV10" else 1
    recording = cal.ActuatorRecording(recording_id="external-core-check", source_recording_id="external-core-check",
        source_file_sha256=result.candidate.csv_sha256, started_at="2026-10-09T00:00:00Z", variable=variable,
        samples=[cal.ActuatorSample(time_s=point.time_s, target_percent_full_scale=value,
            actual_percent_full_scale=point.actual_cooling_setting[index], quality="valid") for point in result.candidate.points])
    assert cal.predict(recording, cal.DEFAULT_TAU_S) == pytest.approx(
        [point.actual_cooling_setting[index] for point in result.candidate.points], abs=1e-10)
