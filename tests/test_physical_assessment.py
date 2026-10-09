"""Check risk missed by short forecasts and conservative sensitivity integration."""
import pytest
from backend.contracts import Command, Scenario, NewRequest
from backend.gateway.service import Gateway
from backend.simulator.service import simulate
from tests.test_simulator import snapshot


def test_delayed_violation_and_analytic_equilibrium():
    row = simulate(Command(target_pct=80), snapshot(), [Scenario(kind="degraded_cooling")]).scenarios[0]
    assert row.candidate_peak_c == pytest.approx(77.268, abs=.001)
    assert not row.exceeded  # This field retains its requested-window meaning.
    assessment = row.physical_assessment
    assert assessment.horizon_s == 3600
    assert assessment.candidate.first_exceeded_s == 378
    assert assessment.candidate.peak_c == pytest.approx(92.305, abs=.001)
    assert assessment.candidate.equilibrium_c == pytest.approx(25+35000/520)
    assert assessment.candidate.thermal_time_constant_s == pytest.approx(200000/520)


def test_joint_parameter_sensitivity_is_explicit_and_deterministic():
    result = simulate(Command(target_pct=80), snapshot(load_ratio=.6), [Scenario(kind="degraded_cooling")])
    a = result.scenarios[0].physical_assessment
    assert result == simulate(Command(target_pct=80), snapshot(load_ratio=.6), [Scenario(kind="degraded_cooling")])
    assert a.calibration_status == "not_calibrated" and a.parameter_origin == "demo_assumption"
    assert a.sensitivity.evaluated_parameter_sets == 16
    assert a.sensitivity.candidate_worst_equilibrium_c == pytest.approx(25+35000*1.1*.6/(1000*.9*.8*.65))
    assert a.sensitivity.candidate_worst_peak_c > a.candidate.peak_c


def test_sensitivity_domain_failure_discards_partial_metrics():
    a = simulate(Command(target_pct=60), snapshot(), [Scenario(kind="degraded_cooling")]).scenarios[0].physical_assessment
    assert a.sensitivity.status == "out_of_domain"
    assert a.sensitivity.candidate_worst_peak_c is None
    assert a.sensitivity.baseline_worst_peak_c is None


def test_long_domain_failure_cannot_look_like_short_pass():
    result = simulate(Command(target_pct=0, duration_s=1), snapshot(), [Scenario(kind="normal")])
    assert result.status == "out_of_domain" and result.scenarios == []
    assert "장기 계산" in result.limitation


@pytest.mark.parametrize("load, speed, verdict", [(1, 80, "blocked"), (1, 100, "blocked"), (.6, 80, "awaiting_approval")])
def test_gateway_honors_long_risk_and_assumed_sensitivity(load, speed, verdict, monkeypatch):
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "fixture")
    gateway = Gateway()
    try:
        gateway.adapter.update_demo_state(load, "valid")
        before = gateway.adapter.read_state()
        row = gateway.create(NewRequest(command={"target_pct": speed}))
        row = gateway.evaluate(row["id"])
        assert row["status"] == verdict
        assert gateway.adapter.read_state() == before
        assert not gateway.adapter.executions
    finally:
        gateway.close()


def test_legacy_or_missing_assessment_cannot_approve(monkeypatch):
    from backend.simulator import service
    original = service.simulate
    def legacy(*args):
        value = original(*args).model_dump()
        for row in value["scenarios"]:
            row.pop("physical_assessment")
        return value
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "fixture")
    monkeypatch.setattr(service, "simulate", legacy)
    gateway = Gateway()
    try:
        gateway.adapter.update_demo_state(.6, "valid")
        row = gateway.create(NewRequest(command={"target_pct": 80}))
        row = gateway.evaluate(row["id"])
        assert row["status"] == "hold" and not row["report"]["can_approve"]
    finally:
        gateway.close()


@pytest.mark.parametrize("change", ["long_peak", "equilibrium", "sensitivity", "coverage"])
def test_approval_rechecks_physical_assessment_even_if_verdict_is_forged(change, monkeypatch):
    from backend.contracts import DecisionInput
    from backend.gateway.evaluation import digest
    from fastapi import HTTPException
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "fixture")
    gateway = Gateway()
    try:
        gateway.adapter.update_demo_state(.6, "valid")
        row = gateway.create(NewRequest(command={"target_pct": 80}))
        row = gateway.evaluate(row["id"])
        assert row["status"] == "awaiting_approval"
        assessment = row["report"]["simulation"]["scenarios"][1]["physical_assessment"]
        if change == "long_peak":
            assessment["candidate"].update(peak_c=81, first_exceeded_s=500)
        elif change == "equilibrium":
            assessment["candidate"]["equilibrium_c"] = 81
        elif change == "sensitivity":
            assessment["sensitivity"]["candidate_worst_equilibrium_c"] = 81
        else:
            assessment["sensitivity"].update(status="out_of_domain", evaluated_parameter_sets=1)
            for key in ("baseline_worst_peak_c", "candidate_worst_peak_c", "baseline_worst_equilibrium_c", "candidate_worst_equilibrium_c"):
                assessment["sensitivity"][key] = None
        row["report"]["digest"] = digest({k: v for k, v in row["report"].items() if k != "digest"})
        gateway.store.save(row)
        with pytest.raises(HTTPException) as error:
            gateway.decide(row["id"], DecisionInput(decision="approve", reason="test", report_digest=row["report"]["digest"]), "approver")
        assert error.value.status_code == 409 and not gateway.adapter.executions
    finally:
        gateway.close()
