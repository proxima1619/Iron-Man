"""Offline parameter fitting with a known thermal capacity and independent recordings.

Temperature alone identifies Q/C and UA/C, not all three absolute quantities.
This tool therefore fixes C to the supplied anchor and never activates its output.
"""
from dataclasses import replace
import hashlib
import json
import math
from typing import Literal
from pydantic import Field, model_validator
from backend.contracts import StrictModel
from backend.simulator.model import MODEL, advance_state


class Measurement(StrictModel):
    time_s: float = Field(ge=0, le=3600)
    temperature_c: float = Field(ge=0, le=120)
    pump_speed_pct: float = Field(ge=0, le=100)
    target_pct: float = Field(ge=0, le=100)
    load_ratio: float = Field(ge=0, le=1.5)


class Recording(StrictModel):
    recording_id: str = Field(min_length=1)
    efficiency: float = Field(default=1, gt=0, le=1)
    samples: list[Measurement] = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def chronology(self):
        times = [p.time_s for p in self.samples]
        if times[0] != 0 or any(b - a < .1 for a, b in zip(times, times[1:])):
            raise ValueError("recording starts at 0; sampling intervals must be at least 0.1 s")
        return self


class CalibrationDataset(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: str = Field(min_length=1)
    data_origin: Literal["synthetic", "measured"]
    candidate_model_version: str = Field(min_length=1)
    thermal_capacity_j_per_k: float = Field(ge=10_000, le=2_000_000)
    capacity_source: str = Field(min_length=1)
    coolant_temperature_c: float = Field(ge=0, le=80)
    coolant_source: str = Field(min_length=1)
    training: list[Recording] = Field(min_length=1, max_length=10)
    validation: list[Recording] = Field(min_length=1, max_length=10)
    max_temperature_rmse_c: float = Field(gt=0, le=10)
    max_temperature_error_c: float = Field(gt=0, le=20)
    max_speed_rmse_pct: float = Field(gt=0, le=10)

    @model_validator(mode="after")
    def separate_validation(self):
        if self.candidate_model_version == MODEL.version:
            raise ValueError("fitted coefficients require a distinct candidate model version")
        runs = self.training + self.validation
        ids = [r.recording_id for r in runs]
        fingerprints = [json.dumps([s.model_dump() for s in r.samples], sort_keys=True) for r in runs]
        if len(ids) != len(set(ids)) or len(fingerprints) != len(set(fingerprints)):
            raise ValueError("training and validation must be separate, nonduplicated recordings")
        if sum(r.samples[-1].time_s for r in runs) > 7200 or sum(len(r.samples) for r in runs) > 4000:
            raise ValueError("offline fitting budget: at most 7200 total seconds and 4000 samples")
        return self


def _bounded_minimum(function, lower, upper):
    """Deterministic golden section search; includes boundary candidates."""
    ratio = (math.sqrt(5) - 1) / 2
    bounds = (lower, upper)
    left, right = upper - ratio * (upper - lower), lower + ratio * (upper - lower)
    fl, fr = function(left), function(right)
    for _ in range(28):
        if fl < fr:
            upper, right, fr = right, left, fl
            left = upper - ratio * (upper - lower)
            fl = function(left)
        else:
            lower, left, fl = left, right, fr
            right = lower + ratio * (upper - lower)
            fr = function(right)
    return min((*bounds, left, right), key=function)


def _errors(recording, model):
    temperature, speed = recording.samples[0].temperature_c, recording.samples[0].pump_speed_pct
    temperature_errors, speed_errors = [], []
    for previous, point in zip(recording.samples, recording.samples[1:]):
        remaining = point.time_s - previous.time_s
        while remaining > 1e-10:
            step = min(1, remaining)
            temperature, speed = advance_state(temperature, speed, previous.target_pct,
                previous.load_ratio, recording.efficiency, step, model=model)
            if not math.isfinite(temperature) or not 0 <= temperature <= 120 or not 0 <= speed <= 100:
                raise ValueError("calibration prediction leaves model state domain")
            remaining -= step
        # Open-loop trajectory, not a reset to the next measured state.
        temperature_errors.append(temperature - point.temperature_c)
        speed_errors.append(speed - point.pump_speed_pct)
    return temperature_errors, speed_errors


def _metrics(runs, model):
    errors = [_errors(run, model) for run in runs]
    temps = [v for pair in errors for v in pair[0]]
    speeds = [v for pair in errors for v in pair[1]]
    return {"temperature_rmse_c": math.sqrt(sum(v*v for v in temps) / len(temps)),
            "temperature_max_error_c": max(abs(v) for v in temps),
            "speed_rmse_pct": math.sqrt(sum(v*v for v in speeds) / len(speeds))}


def _objective(runs, model, key):
    try:
        return _metrics(runs, model)[key]
    except ValueError:
        return math.inf


def _speed_rmse(runs, tau):
    errors = []
    for run in runs:
        speed = run.samples[0].pump_speed_pct
        for previous, point in zip(run.samples, run.samples[1:]):
            speed = previous.target_pct + (speed-previous.target_pct) * math.exp(-(point.time_s-previous.time_s)/tau)
            errors.append(speed-point.pump_speed_pct)
    return math.sqrt(sum(v*v for v in errors)/len(errors))


def calibrate(dataset: CalibrationDataset) -> dict:
    dataset = CalibrationDataset.model_validate(dataset)
    base = replace(MODEL, thermal_capacity_j_per_k=dataset.thermal_capacity_j_per_k,
                   coolant_temperature_c=dataset.coolant_temperature_c)
    # Pump response is independent of temperature. Require observed pump excitation.
    if not any(max(p.pump_speed_pct for p in r.samples) - min(p.pump_speed_pct for p in r.samples) > .1
               and any(abs(p.target_pct-p.pump_speed_pct) > .5 for p in r.samples) for r in dataset.training):
        raise ValueError("training lacks identifiable pump response; add a speed step recording")
    tau = _bounded_minimum(lambda value: _speed_rmse(dataset.training, value), 2, 120)
    base = replace(base, pump_response_s=tau)
    # Integral energy balance provides a starting point and a rank check.
    aa = ab = bb = ay = by = 0.0
    for run in dataset.training:
        for a, b in zip(run.samples, run.samples[1:]):
            dt = b.time_s - a.time_s
            x = a.load_ratio * dt
            y = -dt * run.efficiency * (a.pump_speed_pct / 100 * (a.temperature_c-base.coolant_temperature_c)
                + b.pump_speed_pct / 100 * (b.temperature_c-base.coolant_temperature_c)) / 2
            z = base.thermal_capacity_j_per_k * (b.temperature_c-a.temperature_c)
            aa += x*x; ab += x*y; bb += y*y; ay += x*z; by += y*z
    determinant = aa*bb-ab*ab
    if aa <= 0 or bb <= 0 or determinant <= aa*bb*1e-5:
        raise ValueError("training cannot separate heat input and conductance; vary load and speed")
    heat = (ay*bb-by*ab)/determinant
    conductance = (by*aa-ay*ab)/determinant
    if not 1000 <= heat <= 150000 or not 100 <= conductance <= 5000:
        raise ValueError("energy balance fit leaves supported coefficient bounds")
    model = replace(base, nominal_heat_input_w=heat, full_speed_conductance_w_per_k=conductance)
    # Refine against the same RK4 kernel used by the plant; validation is not used here.
    for _ in range(8):
        for key, low, high in (("nominal_heat_input_w", 1000, 150000), ("full_speed_conductance_w_per_k", 100, 5000)):
            value = _bounded_minimum(lambda v: _objective(dataset.training, replace(model, **{key: v}), "temperature_rmse_c"), low, high)
            model = replace(model, **{key: value})
    training = _metrics(dataset.training, model)
    validation = _metrics(dataset.validation, model)
    passed = (validation["temperature_rmse_c"] <= dataset.max_temperature_rmse_c
              and validation["temperature_max_error_c"] <= dataset.max_temperature_error_c
              and validation["speed_rmse_pct"] <= dataset.max_speed_rmse_pct)
    near_boundary = any(value <= low*1.001 or value >= high*.999 for value, low, high in (
        (model.nominal_heat_input_w, 1000, 150000), (model.full_speed_conductance_w_per_k, 100, 5000),
        (model.pump_response_s, 2, 120)))
    return {"tool_version": "cooling-calibration-v1", "source_id": dataset.source_id,
        "data_origin": dataset.data_origin, "dataset_sha256": hashlib.sha256(
            json.dumps(dataset.model_dump(), sort_keys=True, allow_nan=False).encode()).hexdigest(),
        "candidate_model_version": dataset.candidate_model_version,
        "usage": "offline_candidate_only", "activated": False,
        "anchor": {"thermal_capacity_j_per_k": dataset.thermal_capacity_j_per_k,
                   "capacity_source": dataset.capacity_source, "coolant_temperature_c": dataset.coolant_temperature_c,
                   "coolant_source": dataset.coolant_source},
        "coefficients": {key: getattr(model, key) for key in (
            "nominal_heat_input_w", "full_speed_conductance_w_per_k", "pump_response_s")},
        "training_recording_ids": [r.recording_id for r in dataset.training],
        "validation_recording_ids": [r.recording_id for r in dataset.validation],
        "training_metrics": training, "validation_metrics": validation,
        "validation_thresholds": {key: getattr(dataset, key) for key in (
            "max_temperature_rmse_c", "max_temperature_error_c", "max_speed_rmse_pct")},
        "at_search_boundary": near_boundary, "validation_passed": passed and not near_boundary,
        "limitation": "입력 출처는 사용자가 선언한 값이며 진위를 인증하지 않습니다. C와 냉각수 온도는 고정합니다. "
                      "검증 통과는 해당 기록에 대한 적합도이며 실제 설비 안전·식별 유일성·신뢰구간을 보장하지 않습니다. "
                      "출력 계수는 서버에 자동 적용되지 않습니다. 합성 기록은 물리 정확도 검증이 아닙니다."}
