import pytest
from pydantic import ValidationError
from dataclasses import replace
from backend.simulator.calibration import CalibrationDataset, calibrate
from backend.simulator.model import MODEL
from scripts.generate_calibration_example import example


@pytest.fixture(scope="module")
def fitted():
    return calibrate(example())


def test_identifiable_synthetic_parameters_and_independent_validation(fitted):
    assert fitted["coefficients"]["nominal_heat_input_w"] == pytest.approx(38000, rel=.01)
    assert fitted["coefficients"]["full_speed_conductance_w_per_k"] == pytest.approx(1100, rel=.01)
    assert fitted["coefficients"]["pump_response_s"] == pytest.approx(28, abs=.001)
    assert fitted["validation_passed"] and not fitted["activated"]
    assert fitted["data_origin"] == "synthetic" and fitted["usage"] == "offline_candidate_only"
    assert MODEL.nominal_heat_input_w == 35000  # Fitting does not mutate runtime assumptions.
    assert fitted["training_recording_ids"] != fitted["validation_recording_ids"]


def test_validation_not_used_to_fit_and_bad_validation_rejected(fitted):
    data = example().model_dump()
    for point in data["validation"][0]["samples"]:
        point["temperature_c"] += 8
    bad = calibrate(CalibrationDataset.model_validate(data))
    assert bad["coefficients"] == fitted["coefficients"]
    assert not bad["validation_passed"]
    assert bad["validation_metrics"]["temperature_max_error_c"] > 1


@pytest.mark.parametrize("change", ["duplicate_id", "duplicate_samples", "chronology", "same_version"])
def test_invalid_or_leaking_datasets_rejected(change):
    data = example().model_dump()
    if change == "duplicate_id":
        data["validation"][0]["recording_id"] = data["training"][0]["recording_id"]
    elif change == "duplicate_samples":
        data["validation"][0]["samples"] = data["training"][0]["samples"]
    elif change == "chronology":
        data["training"][0]["samples"][1]["time_s"] = 0
    else:
        data["candidate_model_version"] = MODEL.version
    with pytest.raises(ValidationError):
        CalibrationDataset.model_validate(data)


def test_unexcited_records_cannot_claim_identifiable_parameters():
    data = example().model_dump()
    for point in data["training"][0]["samples"]:
        point.update(pump_speed_pct=100, target_pct=100, temperature_c=60, load_ratio=1)
    with pytest.raises(ValueError, match="pump response"):
        calibrate(CalibrationDataset.model_validate(data))


def test_constant_thermal_regressors_rejected():
    data = example().model_dump()
    for point in data["training"][0]["samples"]:
        point.update(temperature_c=25, load_ratio=0)
    with pytest.raises(ValueError, match="separate heat"):
        calibrate(CalibrationDataset.model_validate(data))


@pytest.mark.parametrize("key, value", [("thermal_capacity_j_per_k", 0), ("pump_response_s", float("nan")), ("degraded_efficiency", 2)])
def test_nonphysical_coefficients_cannot_enter_kernel(key, value):
    with pytest.raises(ValueError):
        replace(MODEL, **{key: value})
