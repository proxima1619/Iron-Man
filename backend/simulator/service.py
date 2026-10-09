"""Owner 2: replace fixture behavior with a validated physical model.
These temperatures and thresholds are UI fixtures, NOT a physical simulation.
"""
from backend.contracts import Command, Snapshot, Scenario, SimulationResult

MODEL_VERSION = "mock-cooling-v1"

def simulate(command: Command, snapshot: Snapshot, scenarios: list[Scenario]) -> SimulationResult:
    rows = []
    for scenario in scenarios:
        # Deliberately simple fixture selection to exercise gateway/UI branches.
        unsafe = command.target_pct < (70 if scenario.kind == "degraded_cooling" else 40)
        rows.append({
            "kind": scenario.kind,
            "evidence_id": scenario.evidence_id,
            "baseline_peak_c": 65,
            "candidate_peak_c": 85 if unsafe else 68,
            "limit_c": 80,
            "exceeded": unsafe,
            "value_origin": "hardcoded_demo_fixture",
        })
    return SimulationResult(mock=True, status="completed", model_version=MODEL_VERSION, scenarios=rows,
        limitation="고정 모의 값입니다. 열수지·시간별 계산·현장 검증은 미구현입니다.")
