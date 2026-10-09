"""Long horizon and explicit assumed-parameter sensitivity, never confidence bounds."""
from dataclasses import replace
from itertools import product
from backend.contracts import BranchAssessment, PhysicalAssessment, SensitivityAssessment
from backend.simulator.model import MODEL
from backend.simulator.service import _run, ModelDomainError

ASSESSMENT_VERSION = "cooling-assessment-v4"
HORIZON_S = 3600
PARAMETER_RANGES = {
    key: {"minimum": getattr(MODEL, key) * .9, "maximum": getattr(MODEL, key) * 1.1}
    for key in ("thermal_capacity_j_per_k", "nominal_heat_input_w",
                "full_speed_conductance_w_per_k", "pump_response_s")
}


def branch(snapshot, target, efficiency, model=MODEL):
    run = _run(snapshot, target, HORIZON_S, efficiency, model=model, collect_series=False)
    conductance = model.full_speed_conductance_w_per_k * target / 100 * efficiency
    if conductance > 0:
        equilibrium = model.coolant_temperature_c + model.nominal_heat_input_w * snapshot.load_ratio / conductance
        status = "finite"
        tau = model.thermal_capacity_j_per_k / conductance
    else:
        equilibrium, tau = None, None
        status = "unbounded_heating" if snapshot.load_ratio > 0 else "no_unique_equilibrium"
    return BranchAssessment(peak_c=run["peak_c"], first_exceeded_s=run["first_exceeded_s"],
        equilibrium_c=equilibrium, equilibrium_status=status, thermal_time_constant_s=tau)


def assess(snapshot, baseline_target, candidate_target, efficiency):
    baseline = branch(snapshot, baseline_target, efficiency)
    candidate = branch(snapshot, candidate_target, efficiency)
    peaks, equilibria = [], []
    completed = 0
    limitation = ("열입력·열전달·열용량·펌프 응답 ±10%의 16개 끝점 조합을 시험합니다. "
                  "범위는 실측값이 아니며 확률·신뢰구간·범위 내 모든 조합을 보장하지 않습니다. "
                  "냉각수 온도·부하·효율은 각 시나리오에서 일정하게 유지합니다.")
    try:
        for values in product(*[(r["minimum"], r["maximum"]) for r in PARAMETER_RANGES.values()]):
            model = replace(MODEL, **dict(zip(PARAMETER_RANGES, values)))
            b = branch(snapshot, baseline_target, efficiency, model)
            c = branch(snapshot, candidate_target, efficiency, model)
            if b.equilibrium_c is None or c.equilibrium_c is None:
                raise ModelDomainError("no finite equilibrium for sensitivity comparison")
            peaks.append((b.peak_c, c.peak_c))
            equilibria.append((b.equilibrium_c, c.equilibrium_c))
            completed += 1
        sensitivity = SensitivityAssessment(status="completed", evaluated_parameter_sets=completed,
            baseline_worst_peak_c=max(p[0] for p in peaks), candidate_worst_peak_c=max(p[1] for p in peaks),
            baseline_worst_equilibrium_c=max(p[0] for p in equilibria),
            candidate_worst_equilibrium_c=max(p[1] for p in equilibria), limitation=limitation)
    except ModelDomainError as exc:
        sensitivity = SensitivityAssessment(status="out_of_domain", evaluated_parameter_sets=completed,
            limitation=f"{limitation} 일부 조합을 지원하지 못해 전체 민감도 수치를 반환하지 않습니다: {exc}")
    return PhysicalAssessment(horizon_s=HORIZON_S, baseline=baseline, candidate=candidate,
        parameter_ranges=PARAMETER_RANGES, sensitivity=sensitivity)
