"""Deterministic, synthetic cooling-tank model for the virtual demo only."""

import math

from backend.contracts import Command, Scenario, SimulationResult, Snapshot
from backend.simulator.model import MODEL, advance_state

MODEL_VERSION = MODEL.version
LIMIT_C = MODEL.limit_c
DT_S = MODEL.dt_s
DEGRADED_EFFICIENCY = MODEL.degraded_efficiency


class ModelDomainError(ValueError):
    """A calculated state leaves the supported domain; do not publish partial metrics."""


def _check_state(temperature_c: float, speed_pct: float, time_s: float) -> None:
    for name, value, low, high in (
        ("temperature_c", temperature_c, MODEL.temperature_min_c, MODEL.temperature_max_c),
        ("pump_speed_pct", speed_pct, 0.0, 100.0),
    ):
        if not math.isfinite(value) or not low <= value <= high:
            raise ModelDomainError(
                f"out_of_domain:{name}, time_s={time_s:g}, value={value:g}, range=[{low:g}, {high:g}]")


def _run(snapshot: Snapshot, target_pct: float, duration_s: int,
         efficiency: float, *, dt_s: float = DT_S) -> dict:
    if not math.isfinite(dt_s) or not 0 < dt_s <= MODEL.dt_s:
        raise ValueError("dt_s must be finite and in (0, 1] seconds")
    temperature = snapshot.temperature_c
    effective_speed = snapshot.pump_speed_pct
    _check_state(temperature, effective_speed, 0)
    series = [{"time_s": 0, "temperature_c": temperature,
               "pump_speed_pct": effective_speed}]
    peak = temperature
    first_exceeded = 0 if temperature > LIMIT_C else None
    elapsed_s = 0.0
    for index in range(math.ceil(duration_s / dt_s)):
        next_time_s = min(duration_s, (index + 1) * dt_s)
        temperature, effective_speed = advance_state(
            temperature, effective_speed, target_pct, snapshot.load_ratio,
            efficiency, next_time_s - elapsed_s)
        elapsed_s = next_time_s
        _check_state(temperature, effective_speed, elapsed_s)
        peak = max(peak, temperature)
        if first_exceeded is None and temperature > LIMIT_C:
            first_exceeded = elapsed_s
        series.append({"time_s": round(elapsed_s, 10), "temperature_c": temperature,
                       "pump_speed_pct": effective_speed})
    return {"series": series, "peak_c": peak,
            "first_exceeded_s": first_exceeded}


def domain_reasons(snapshot: Snapshot) -> list[str]:
    """The forecast and virtual plant use the same supported input domain."""
    reasons = []
    if snapshot.domain_status != "ready":
        reasons.append(snapshot.domain_reason or "virtual_plant_out_of_domain")
    if snapshot.model_version is not None and snapshot.model_version != MODEL_VERSION:
        reasons.append("unsupported_snapshot_model_version")
    if snapshot.sensor_quality != "valid":
        reasons.append("invalid_sensor_quality")
    for name, value, low, high in (
        ("temperature_c", snapshot.temperature_c, MODEL.temperature_min_c, MODEL.temperature_max_c),
        ("load_ratio", snapshot.load_ratio, 0, 1.5),
        ("pump_speed_pct", snapshot.pump_speed_pct, 0, 100),
        ("target_pump_speed_pct", snapshot.target_pump_speed_pct if snapshot.target_pump_speed_pct is not None
         else snapshot.pump_speed_pct, 0, 100),
    ):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            reasons.append(f"out_of_domain:{name}")
    if not math.isfinite(snapshot.observed_at) or snapshot.observed_at <= 0:
        reasons.append("invalid_observation_time")
    return reasons


def simulate(command: Command, snapshot: Snapshot, scenarios: list[Scenario],
             model_version: str = MODEL_VERSION) -> SimulationResult:
    """Compare keeping the current target with the requested target, from identical actual states."""
    if model_version != MODEL_VERSION:
        raise ValueError(f"Unsupported model version: {model_version}")
    reasons = domain_reasons(snapshot)
    limitation = (f"합성 상태·데모 계수의 열수지 모델 v3입니다. 열용량 {MODEL.thermal_capacity_j_per_k:g} J/K, "
                  f"기준 열입력 {MODEL.nominal_heat_input_w:g} W, "
                  f"전속도 열교환계수 {MODEL.full_speed_conductance_w_per_k:g} W/K, "
                  f"냉각수 {MODEL.coolant_temperature_c:g}°C를 가정합니다. "
                  "실제 설비·센서·전력 사용량의 정확도를 검증하지 않았습니다. "
                  "기준 시험은 현재 목표 속도를 유지하며, 두 시험은 같은 실제 속도·온도에서 시작합니다. "
                  "duration_s는 예측 구간이며 실행된 목표 속도의 자동 만료 시간이 아닙니다. "
                  "시계열은 현 v1 API 계약에 포함되지 않습니다.")
    if reasons:
        return SimulationResult(mock=False, status="out_of_domain",
            model_version=MODEL_VERSION, scenarios=[],
            limitation=f"{limitation} 입력 부적합: {', '.join(reasons)}")
    if not scenarios:
        return SimulationResult(mock=False, status="failed", model_version=MODEL_VERSION,
            scenarios=[], limitation=f"{limitation} 요청한 시험 조건이 없습니다.")
    rows = []
    for scenario in scenarios:
        efficiency = DEGRADED_EFFICIENCY if scenario.kind == "degraded_cooling" else 1.0
        runs = {}
        baseline_target = (snapshot.target_pump_speed_pct if snapshot.target_pump_speed_pct is not None
                           else snapshot.pump_speed_pct)
        for branch, speed in (("baseline", baseline_target), ("candidate", command.target_pct)):
            try:
                runs[branch] = _run(snapshot, speed, command.duration_s, efficiency)
            except ModelDomainError as exc:
                return SimulationResult(mock=False, status="out_of_domain",
                    model_version=MODEL_VERSION, scenarios=[],
                    limitation=f"{limitation} 계산 범위 초과: {scenario.kind}/{branch}: {exc}")
        baseline, candidate = runs["baseline"], runs["candidate"]
        rows.append({"kind": scenario.kind, "evidence_id": scenario.evidence_id,
                     "baseline_peak_c": baseline["peak_c"],
                     "candidate_peak_c": candidate["peak_c"],
                     "limit_c": LIMIT_C,
                     "exceeded": candidate["peak_c"] > LIMIT_C,
                     "value_origin": "model_calculation"})
    return SimulationResult(mock=False, status="completed", model_version=MODEL_VERSION,
                            scenarios=rows, limitation=limitation)
