import pytest

from backend.contracts import Command, Scenario, Snapshot
from backend.simulator.service import _run, simulate
from backend.gateway.service import Gateway
from backend.contracts import NewRequest


def snapshot(**changes):
    values = dict(revision=1, temperature_c=60, load_ratio=1,
                  pump_speed_pct=100, observed_at=1)
    values.update(changes)
    return Snapshot(**values)


def test_reproducible_equal_initial_conditions_and_counterexample():
    scenarios = [Scenario(kind="normal"),
                 Scenario(kind="degraded_cooling", evidence_id="demo-counterexample")]
    result = simulate(Command(target_pct=60), snapshot(), scenarios)
    assert result == simulate(Command(target_pct=60), snapshot(), scenarios)
    assert result.status == "completed"
    assert result.mock is False
    normal, degraded = result.scenarios
    assert normal.exceeded is False
    assert degraded.exceeded is True
    assert degraded.evidence_id == "demo-counterexample"
    trace = _run(snapshot(), 60, 300, 0.65)
    assert trace["series"][0]["temperature_c"] == 60
    assert trace["first_exceeded_s"] is not None
    assert len(trace["series"]) == 301


def test_more_pump_cooling_does_not_raise_temperature():
    slow = simulate(Command(target_pct=60), snapshot(), [Scenario(kind="normal")]).scenarios[0]
    fast = simulate(Command(target_pct=80), snapshot(), [Scenario(kind="normal")]).scenarios[0]
    assert fast.candidate_peak_c < slow.candidate_peak_c


@pytest.mark.parametrize("changes, reason", [
    ({"sensor_quality": "invalid"}, "invalid_sensor_quality"),
    ({"load_ratio": 2}, "out_of_domain:load_ratio"),
    ({"observed_at": 0}, "invalid_observation_time"),
])
def test_bad_input_is_unsupported_not_safe(changes, reason):
    result = simulate(Command(target_pct=80), snapshot(**changes),
                      [Scenario(kind="normal")])
    assert result.status == "out_of_domain"
    assert reason in result.limitation
    assert result.scenarios == []


def test_unknown_model_version_rejected():
    with pytest.raises(ValueError):
        simulate(Command(target_pct=80), snapshot(), [Scenario(kind="normal")], "unknown")


def test_real_calculation_without_live_policy_holds_virtual_execution():
    gateway = Gateway()
    row = gateway.create(NewRequest(command=Command(target_pct=80)))
    evaluated = gateway.evaluate(row["id"])
    assert evaluated["status"] == "hold"
    assert evaluated["report"]["reason_code"] == "LIVE_POLICY_NOT_CONFIGURED"
    assert evaluated["report"]["simulation"]["mock"] is False
    assert gateway.adapter.executions == {}
