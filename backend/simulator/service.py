"""Deterministic, synthetic cooling-tank model for the virtual demo only."""

import math

from backend.contracts import Command, Scenario, SimulationResult, Snapshot

MODEL_VERSION = "cooling-demo-v1"
LIMIT_C = 80.0
DT_S = 1
DEGRADED_EFFICIENCY = 0.65
HEAT_GAIN_C_PER_S = 0.15
COOLING_GAIN_C_PER_S_PER_PCT = 0.002
PUMP_RESPONSE_S = 20.0


def _run(snapshot: Snapshot, target_pct: float, duration_s: int,
         efficiency: float) -> dict:
    temperature = snapshot.temperature_c
    effective_speed = snapshot.pump_speed_pct
    series = [{"time_s": 0, "temperature_c": round(temperature, 4)}]
    peak = temperature
    first_exceeded = 0 if temperature > LIMIT_C else None
    for second in range(1, duration_s + 1):
        effective_speed += (target_pct - effective_speed) * DT_S / PUMP_RESPONSE_S
        temperature += DT_S * (
            HEAT_GAIN_C_PER_S * snapshot.load_ratio
            - COOLING_GAIN_C_PER_S_PER_PCT * effective_speed * efficiency
        )
        peak = max(peak, temperature)
        if first_exceeded is None and temperature > LIMIT_C:
            first_exceeded = second
        series.append({"time_s": second, "temperature_c": round(temperature, 4)})
    return {"series": series, "peak_c": peak,
            "first_exceeded_s": first_exceeded}


def simulate(command: Command, snapshot: Snapshot, scenarios: list[Scenario],
             model_version: str = MODEL_VERSION) -> SimulationResult:
    """Compare unchanged and requested speed under each identical scenario."""
    if model_version != MODEL_VERSION:
        raise ValueError(f"Unsupported model version: {model_version}")
    reasons = []
    if snapshot.sensor_quality != "valid":
        reasons.append("invalid_sensor_quality")
    for name, value, low, high in (
        ("temperature_c", snapshot.temperature_c, 0, 120),
        ("load_ratio", snapshot.load_ratio, 0, 1.5),
        ("pump_speed_pct", snapshot.pump_speed_pct, 0, 100),
    ):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            reasons.append(f"out_of_domain:{name}")
    if not math.isfinite(snapshot.observed_at) or snapshot.observed_at <= 0:
        reasons.append("invalid_observation_time")
    limitation = ("합성 초기 상태와 단순 열수지 모델입니다. 실제 설비·센서·전력 사용량의 "
                  "정확도를 검증하지 않았습니다. 시계열은 현 v1 API 계약에 포함되지 않습니다.")
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
        baseline = _run(snapshot, snapshot.pump_speed_pct, command.duration_s, efficiency)
        candidate = _run(snapshot, command.target_pct, command.duration_s, efficiency)
        rows.append({"kind": scenario.kind, "evidence_id": scenario.evidence_id,
                     "baseline_peak_c": baseline["peak_c"],
                     "candidate_peak_c": candidate["peak_c"],
                     "limit_c": LIMIT_C,
                     "exceeded": candidate["peak_c"] > LIMIT_C,
                     "value_origin": "model_calculation"})
    return SimulationResult(mock=False, status="completed", model_version=MODEL_VERSION,
                            scenarios=rows, limitation=limitation)
