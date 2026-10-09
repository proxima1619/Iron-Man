"""Use owner 2's current model and domain, never invent a fault parameter."""
from backend.contracts import NewRequest, Snapshot
from backend.simulator import service as simulator


def review_context(request: NewRequest, snapshot: Snapshot) -> dict:
    current_target = (snapshot.target_pump_speed_pct if snapshot.target_pump_speed_pct is not None
                      else snapshot.pump_speed_pct)
    return {
        "temperature_c": snapshot.temperature_c,
        "actual_pump_speed_pct": snapshot.pump_speed_pct,
        "current_target_pump_speed_pct": current_target,
        "current_target_origin": "snapshot" if snapshot.target_pump_speed_pct is not None else "legacy_actual_speed_fallback",
        "requested_target_pump_speed_pct": request.command.target_pct,
        "speed_gap_percentage_points": current_target - snapshot.pump_speed_pct,
        "load_ratio": snapshot.load_ratio,
        "forecast_horizon_s": request.command.duration_s,
        "simulation_time_s": snapshot.simulation_time_s,
        "model_version": simulator.MODEL_VERSION,
        "domain_reasons": simulator.domain_reasons(snapshot),
        "units": {"temperature_c": "degC", "speed": "%", "speed_gap": "percentage_points",
                  "load_ratio": "dimensionless", "time": "s", "efficiency": "dimensionless"},
        "supported_tests": [{"kind": "degraded_cooling", "efficiency": simulator.DEGRADED_EFFICIENCY,
                             "parameter_origin": "demo_assumption", "parameter_owner": "simulator"}],
    }


def context_description(context: dict) -> str:
    return (f"검토 입력: 현재 온도 {context['temperature_c']:g}°C, 실제 속도 "
            f"{context['actual_pump_speed_pct']:g}%, 기존 목표 {context['current_target_pump_speed_pct']:g}%, "
            f"요청 목표 {context['requested_target_pump_speed_pct']:g}%, 부하 {context['load_ratio']:g}, "
            f"가상 시각 {context['simulation_time_s']:g}s, 예측 구간 {context['forecast_horizon_s']}s, "
            f"모델 {context['model_version']}. 기존 목표 출처: {context['current_target_origin']}.")
