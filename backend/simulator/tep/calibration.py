"""Offline fit of the two TEP cooling actuator response times.

The pinned TEFUNC actuator equation is d(vpos)/dt = (vcv-vpos)/vtau.
With no actuator faults, vcv is the bounded recorded command. We use the
same 0.1 s Euler discretization as runner.cpp; chemistry is not fitted.
"""
from datetime import timedelta
import hashlib
import json
import math
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from backend.contracts import StrictModel
from .build import sha, source_lock
from .service import MODEL_VERSION

Channel = Literal["XMV10", "XMV11"]
STEP_S = 0.1
DEFAULT_TAU_S = 5.0  # TEINIT vtau[9], vtau[10], divided by 3600 for core hours.
TOOL_VERSION = "tep-actuator-calibration-v1"


class ActuatorSample(StrictModel):
    time_s: float = Field(ge=0, le=3600, strict=True)
    target_percent_full_scale: float = Field(ge=0, le=100, strict=True)
    actual_percent_full_scale: float = Field(ge=0, le=100, strict=True)
    quality: Literal["valid"]


class ActuatorRecording(StrictModel):
    recording_id: str = Field(min_length=1)
    source_recording_id: str = Field(min_length=1)
    source_file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    started_at: AwareDatetime
    variable: Channel
    samples: list[ActuatorSample] = Field(min_length=4, max_length=2000)

    @model_validator(mode="after")
    def chronology(self):
        times = [sample.time_s for sample in self.samples]
        if times[0] != 0 or any(b - a < STEP_S - 1e-9 for a, b in zip(times, times[1:])):
            raise ValueError("recordings must start at 0 with increasing times at least 0.1 s apart")
        if any(abs(time * 10 - round(time * 10)) > 1e-7 for time in times):
            raise ValueError("timestamps must be explicitly aligned to the 0.1 s model grid")
        return self


class ActuatorChannel(StrictModel):
    unit: Literal["percent_full_scale"]
    target_tag: str = Field(min_length=1)
    actual_tag: str = Field(min_length=1)
    normalization_reference: str = Field(min_length=1)
    minimum_tau_s: float = Field(ge=1, le=120, strict=True)
    maximum_tau_s: float = Field(ge=1, le=120, strict=True)
    max_validation_rmse: float = Field(gt=0, le=10, strict=True)
    max_validation_abs_error: float = Field(gt=0, le=20, strict=True)
    actual_resolution: float = Field(gt=0, le=1, strict=True)

    @model_validator(mode="after")
    def bounds_and_tags(self):
        if self.minimum_tau_s >= self.maximum_tau_s:
            raise ValueError("response-time search bounds must be increasing")
        if self.target_tag == self.actual_tag:
            raise ValueError("recorded XMV commands are not independent actuator feedback")
        return self


class TEPActuatorCalibrationDataset(StrictModel):
    schema_version: Literal["tep-actuator-calibration-1.0"] = "tep-actuator-calibration-1.0"
    source_id: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    data_origin: Literal["measured", "simulation"]
    mapping_status: Literal["user_confirmed_actuator_mapping"]
    actuator_faults: Literal["none"]
    source_model_version: Literal["nist-tep-81a7ac9-ironman-v1"] = MODEL_VERSION
    candidate_model_version: str = Field(min_length=1)
    channels: dict[Channel, ActuatorChannel] = Field(min_length=1, max_length=2)
    training: list[ActuatorRecording] = Field(min_length=1, max_length=20)
    validation: list[ActuatorRecording] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def independent_recordings(self):
        if self.candidate_model_version == MODEL_VERSION:
            raise ValueError("candidate must have a distinct model version")
        if {r.variable for r in self.training} != set(self.channels) or {r.variable for r in self.validation} != set(self.channels):
            raise ValueError("each configured channel needs training and independent validation recordings")
        runs = self.training + self.validation
        ids = [run.recording_id for run in runs]
        fingerprints = [canonical_sha([p.model_dump() for p in run.samples]) for run in runs]
        if len(ids) != len(set(ids)) or len(fingerprints) != len(set(fingerprints)):
            raise ValueError("recordings and samples must not be duplicated")
        if {r.source_recording_id for r in self.training} & {r.source_recording_id for r in self.validation}:
            raise ValueError("training and validation must use different source experiments")
        for train in self.training:
            for valid in self.validation:
                if train.variable != valid.variable:
                    continue
                train_end = train.started_at + timedelta(seconds=train.samples[-1].time_s)
                valid_end = valid.started_at + timedelta(seconds=valid.samples[-1].time_s)
                if train.started_at <= valid_end and valid.started_at <= train_end:
                    raise ValueError("training and validation acquisition windows must not overlap")
        if sum(len(run.samples) for run in runs) > 8000:
            raise ValueError("offline fitting supports at most 8000 samples")
        return self


class ActuatorErrors(StrictModel):
    sample_count: int = Field(gt=0)
    unit: Literal["percent_full_scale"] = "percent_full_scale"
    bias: float
    rmse: float = Field(ge=0)
    maximum_abs_error: float = Field(ge=0)


class ActuatorFit(StrictModel):
    parameter: Literal["actuator_response_time"] = "actuator_response_time"
    unit: Literal["s"] = "s"
    tau_s: float = Field(ge=1, le=120)
    runtime_default_tau_s: Literal[5.0] = 5.0
    training_errors: ActuatorErrors
    validation_errors: ActuatorErrors
    default_validation_errors: ActuatorErrors
    nearby_prediction_change: float = Field(ge=0)
    nearby_prediction_change_unit: Literal["percent_full_scale"] = "percent_full_scale"
    diagnostic_scope: Literal["local_sensitivity_not_confidence_interval"] = "local_sensitivity_not_confidence_interval"
    at_search_boundary: bool
    validation_passed: bool
    rejection_reasons: list[str]


class TEPActuatorCalibrationResult(StrictModel):
    schema_version: Literal["tep-actuator-calibration-result-1.0"] = "tep-actuator-calibration-result-1.0"
    tool_version: Literal["tep-actuator-calibration-v1"] = TOOL_VERSION
    status: Literal["candidate_ready", "candidate_rejected", "failed"]
    usage: Literal["offline_candidate_only"] = "offline_candidate_only"
    activated: Literal[False] = False
    can_approve: Literal[False] = False
    validation_scope: Literal["cooling_actuator_response_only"] = "cooling_actuator_response_only"
    whole_process_field_validation: Literal["not_performed"] = "not_performed"
    source_authentication: Literal["user_declared_not_authenticated"] = "user_declared_not_authenticated"
    data_origin: Literal["measured", "simulation"] | None = None
    candidate_model_version: str | None = None
    input_file_sha256: str | None = None
    canonical_dataset_sha256: str | None = None
    provenance: dict = Field(default_factory=dict)
    fitted_parameters: dict[Channel, ActuatorFit] = Field(default_factory=dict)
    failure_code: str | None = None
    detail: str

    @model_validator(mode="after")
    def result_status(self):
        if self.status == "failed":
            if self.fitted_parameters or not self.failure_code:
                raise ValueError("failed calibration must not publish fitted parameters")
        else:
            if not self.fitted_parameters or not self.provenance or not self.canonical_dataset_sha256 or self.failure_code:
                raise ValueError("candidate requires parameters and provenance")
            if (self.status == "candidate_ready") != all(p.validation_passed for p in self.fitted_parameters.values()):
                raise ValueError("candidate status must match independent validation")
        return self


def canonical_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def predict(run: ActuatorRecording, tau_s: float) -> list[float]:
    if not math.isfinite(tau_s) or not 1 <= tau_s <= 120:
        raise ValueError("unsupported response time")
    actual = run.samples[0].actual_percent_full_scale
    trajectory = [actual]
    for previous, point in zip(run.samples, run.samples[1:]):
        steps = round((point.time_s - previous.time_s) / STEP_S)
        target = previous.target_percent_full_scale
        actual = target + (actual - target) * (1 - STEP_S / tau_s) ** steps
        trajectory.append(actual)
    return trajectory


def errors(runs: list[ActuatorRecording], tau_s: float) -> ActuatorErrors:
    residuals = [predicted - point.actual_percent_full_scale
        for run in runs for predicted, point in zip(predict(run, tau_s)[1:], run.samples[1:])]
    return ActuatorErrors(sample_count=len(residuals), bias=math.fsum(residuals) / len(residuals),
        rmse=math.sqrt(math.fsum(value * value for value in residuals) / len(residuals)),
        maximum_abs_error=max(abs(value) for value in residuals))


def bounded_minimum(function, lower, upper):
    # Scan first: a noisy/multi-step record need not have a globally unimodal loss.
    grid = [lower + (upper - lower) * i / 32 for i in range(33)]
    best_index = min(range(len(grid)), key=lambda i: function(grid[i]))
    bounds = (lower, upper, grid[best_index])
    lower, upper = grid[max(0, best_index - 1)], grid[min(32, best_index + 1)]
    ratio = (math.sqrt(5) - 1) / 2
    left, right = upper - ratio * (upper - lower), lower + ratio * (upper - lower)
    fl, fr = function(left), function(right)
    for _ in range(40):
        if fl < fr:
            upper, right, fr = right, left, fl
            left = upper - ratio * (upper - lower)
            fl = function(left)
        else:
            lower, left, fl = left, right, fr
            right = lower + ratio * (upper - lower)
            fr = function(right)
    return min((*bounds, left, right), key=function)


def fit(dataset: TEPActuatorCalibrationDataset) -> TEPActuatorCalibrationResult:
    dataset = TEPActuatorCalibrationDataset.model_validate(dataset)
    lock = source_lock()  # Candidate belongs to these exact model equations.
    fitted = {}
    for variable, channel in dataset.channels.items():
        training = [run for run in dataset.training if run.variable == variable]
        validation = [run for run in dataset.validation if run.variable == variable]
        if not any(max(p.actual_percent_full_scale for p in run.samples) - min(p.actual_percent_full_scale for p in run.samples) > channel.actual_resolution
                   and any(abs(p.target_percent_full_scale - p.actual_percent_full_scale) > channel.actual_resolution for p in run.samples[:-1])
                   for run in training):
            raise ValueError(f"{variable}: training lacks an observable actuator transient")
        tau = bounded_minimum(lambda value: errors(training, value).rmse,
                              channel.minimum_tau_s, channel.maximum_tau_s)
        low, high = max(channel.minimum_tau_s, tau * .95), min(channel.maximum_tau_s, tau * 1.05)
        sensitivity = max(abs(a-b) for run in training for a, b in zip(predict(run, low)[1:], predict(run, high)[1:]))
        at_boundary = min(tau-channel.minimum_tau_s, channel.maximum_tau_s-tau) < (channel.maximum_tau_s-channel.minimum_tau_s) * .001
        valid, default = errors(validation, tau), errors(validation, DEFAULT_TAU_S)
        reasons = []
        if at_boundary: reasons.append("FIT_AT_SEARCH_BOUNDARY")
        if sensitivity < channel.actual_resolution: reasons.append("WEAK_PARAMETER_SENSITIVITY")
        if valid.rmse > channel.max_validation_rmse or valid.maximum_abs_error > channel.max_validation_abs_error:
            reasons.append("VALIDATION_ERROR_EXCEEDED")
        if valid.rmse > default.rmse + channel.actual_resolution:
            reasons.append("VALIDATION_WORSE_THAN_DEFAULT")
        fitted[variable] = ActuatorFit(tau_s=tau, training_errors=errors(training, tau),
            validation_errors=valid, default_validation_errors=default,
            nearby_prediction_change=sensitivity, at_search_boundary=at_boundary,
            validation_passed=not reasons, rejection_reasons=reasons)
    return TEPActuatorCalibrationResult(
        status="candidate_ready" if all(value.validation_passed for value in fitted.values()) else "candidate_rejected",
        data_origin=dataset.data_origin, candidate_model_version=dataset.candidate_model_version,
        canonical_dataset_sha256=canonical_sha(dataset.model_dump(mode="json")), fitted_parameters=fitted,
        provenance={"source_url": lock["repository"], "source_commit": lock["commit"],
            "source_files_sha256": lock["files"], "tool_sha256": sha(__file__),
            "source_id": dataset.source_id, "source_uri": dataset.source_uri, "asset_id": dataset.asset_id,
            "source_model_version": dataset.source_model_version, "component_model_version": TOOL_VERSION,
            "mapping_status": dataset.mapping_status, "actuator_faults": dataset.actuator_faults,
            "equation": "actual_next = target + (actual - target) * (1 - 0.1 / tau_s) ** steps",
            "integration_step_s": STEP_S, "integrator": "forward_euler_closed_form",
            "target_timing": "command takes effect immediately after its sample timestamp",
            "parameter_locator": "teprob.cpp: TEINIT vtau[9]/vtau[10]; TEFUNC yp[48]/yp[49] (1-based)",
            "internal_state_indices_zero_based": {"XMV10": 47, "XMV11": 48},
            "random_seed": None, "random_seed_reason": "deterministic actuator component; full TE process not executed",
            "channels": {key: value.model_dump() for key, value in dataset.channels.items()},
            "recordings": [{"recording_id": run.recording_id, "source_recording_id": run.source_recording_id,
                "source_file_sha256": run.source_file_sha256, "started_at": run.started_at.isoformat(),
                "variable": run.variable, "duration_s": run.samples[-1].time_s,
                "observation_count": len(run.samples), "initial_actual_percent_full_scale": run.samples[0].actual_percent_full_scale,
                "split": "training" if run in dataset.training else "validation"} for run in dataset.training + dataset.validation]},
        detail="TEP 냉각수 액추에이터 응답시간의 오프라인 후보입니다. 단위·태그·출처는 사용자 선언이며 진위를 인증하지 않습니다. "
               "온도·압력·열전달 등 전체 공정 계수를 보정하거나 전체 초기 상태를 복원하지 않습니다. "
               "시뮬레이션 자료의 통과는 실측 검증이 아닙니다. 후보는 런타임·승인 정책에 적용되지 않습니다.")
