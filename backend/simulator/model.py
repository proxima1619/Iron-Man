"""Versioned physical balance with assumed demo parameters, not plant calibration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CoolingModel:
    version: str = "cooling-demo-v3"
    thermal_capacity_j_per_k: float = 200_000.0
    nominal_heat_input_w: float = 35_000.0
    full_speed_conductance_w_per_k: float = 1_000.0
    coolant_temperature_c: float = 25.0
    pump_response_s: float = 20.0
    degraded_efficiency: float = 0.65
    temperature_min_c: float = 0.0
    temperature_max_c: float = 120.0
    limit_c: float = 80.0
    dt_s: float = 1.0


MODEL = CoolingModel()


def advance_state(temperature_c: float, speed_pct: float, target_pct: float,
                  load_ratio: float, efficiency: float, step_s: float) -> tuple[float, float]:
    """One RK4 step of the coupled tank temperature and actual pump speed."""
    def rates(temperature: float, speed: float) -> tuple[float, float]:
        heat_input_w = MODEL.nominal_heat_input_w * load_ratio
        conductance_w_per_k = MODEL.full_speed_conductance_w_per_k * speed / 100 * efficiency
        heat_removed_w = conductance_w_per_k * (temperature - MODEL.coolant_temperature_c)
        return ((heat_input_w - heat_removed_w) / MODEL.thermal_capacity_j_per_k,
                (target_pct - speed) / MODEL.pump_response_s)

    t1, n1 = rates(temperature_c, speed_pct)
    t2, n2 = rates(temperature_c + step_s * t1 / 2, speed_pct + step_s * n1 / 2)
    t3, n3 = rates(temperature_c + step_s * t2 / 2, speed_pct + step_s * n2 / 2)
    t4, n4 = rates(temperature_c + step_s * t3, speed_pct + step_s * n3)
    return (temperature_c + step_s * (t1 + 2 * t2 + 2 * t3 + t4) / 6,
            speed_pct + step_s * (n1 + 2 * n2 + 2 * n3 + n4) / 6)
