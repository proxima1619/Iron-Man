import math

import pytest

from backend.contracts import Command, Scenario, Snapshot
from backend.simulator.model import MODEL
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


def test_real_calculation_waits_for_human_virtual_approval():
    gateway = Gateway()
    try:
        row = gateway.create(NewRequest(command=Command(target_pct=80)))
        evaluated = gateway.evaluate(row["id"])
        assert evaluated["status"] == "awaiting_approval"
        assert evaluated["report"]["reason_code"] == "DEMO_PASS"
        assert evaluated["report"]["simulation"]["mock"] is False
        assert gateway.adapter.executions == {}
    finally:
        gateway.close()


def test_constant_speed_matches_analytic_heat_balance():
    state = snapshot(temperature_c=70, load_ratio=0.8)
    duration = 300
    equilibrium = MODEL.coolant_temperature_c + (
        MODEL.nominal_heat_input_w * state.load_ratio / MODEL.full_speed_conductance_w_per_k)
    expected = equilibrium + (state.temperature_c - equilibrium) * math.exp(
        -MODEL.full_speed_conductance_w_per_k * duration / MODEL.thermal_capacity_j_per_k)
    trace = _run(state, 100, duration, 1)
    assert trace["series"][-1]["temperature_c"] == pytest.approx(expected, abs=1e-8)


@pytest.mark.parametrize("initial_c", [10, 60])
def test_zero_load_approaches_coolant_without_overshoot(initial_c):
    trace = _run(snapshot(temperature_c=initial_c, load_ratio=0), 100, 3600, 1)
    temperatures = [point["temperature_c"] for point in trace["series"]]
    assert min(temperatures) >= min(initial_c, MODEL.coolant_temperature_c)
    assert max(temperatures) <= max(initial_c, MODEL.coolant_temperature_c)
    assert temperatures[-1] == pytest.approx(MODEL.coolant_temperature_c, abs=1e-5)


def test_nominal_state_remains_in_thermal_equilibrium_for_one_hour():
    trace = _run(snapshot(), 100, 3600, 1)
    assert all(point["temperature_c"] == 60 for point in trace["series"])


@pytest.mark.parametrize("load_ratio", [0, 1])
def test_no_pump_has_only_heat_input(load_ratio):
    state = snapshot(pump_speed_pct=0, load_ratio=load_ratio)
    trace = _run(state, 0, 100, 1)
    expected = 60 + MODEL.nominal_heat_input_w * load_ratio * 100 / MODEL.thermal_capacity_j_per_k
    assert trace["series"][-1]["temperature_c"] == pytest.approx(expected, abs=1e-10)


def test_step_refinement_preserves_horizon_and_converges_with_pump_lag():
    traces = [_run(snapshot(), 60, 301, 0.65, dt_s=step) for step in (1, 0.5, 0.3)]
    assert all(trace["series"][-1]["time_s"] == 301 for trace in traces)
    assert traces[0]["series"][-1]["temperature_c"] == pytest.approx(
        traces[-1]["series"][-1]["temperature_c"], abs=1e-5)
    # Actual speed follows the 20 s lag rather than jumping to the target.
    expected_speed_at_20s = 60 + 40 * math.exp(-1)
    assert traces[0]["series"][20]["pump_speed_pct"] == pytest.approx(expected_speed_at_20s, abs=1e-5)


@pytest.mark.parametrize("step", [0, 2])
def test_unsupported_integration_step_is_rejected(step):
    with pytest.raises(ValueError):
        _run(snapshot(), 80, 300, 1, dt_s=step)


@pytest.mark.parametrize("initial_c, exceeded", [(80, False), (80.000001, True)])
def test_peak_includes_initial_temperature_and_uses_strict_limit(initial_c, exceeded):
    row = simulate(Command(target_pct=100), snapshot(temperature_c=initial_c, load_ratio=0),
                   [Scenario(kind="normal")]).scenarios[0]
    assert row.candidate_peak_c == initial_c
    assert row.exceeded is exceeded


def test_runtime_domain_failure_in_baseline_returns_no_metrics():
    result = simulate(Command(target_pct=100, duration_s=600), snapshot(pump_speed_pct=0),
                      [Scenario(kind="normal")])
    assert result.status == "out_of_domain"
    assert result.scenarios == []
    assert "normal/baseline" in result.limitation
    assert "time_s=343" in result.limitation


def test_runtime_domain_failure_in_candidate_returns_no_partial_scenarios():
    command = Command(target_pct=40, duration_s=3600)
    assert simulate(command, snapshot(), [Scenario(kind="normal")]).status == "completed"
    result = simulate(command, snapshot(),
                      [Scenario(kind="normal"), Scenario(kind="degraded_cooling")])
    assert result.status == "out_of_domain"
    assert result.scenarios == []
    assert "degraded_cooling/candidate" in result.limitation
    assert "out_of_domain:temperature_c" in result.limitation


def test_unsupported_forecast_holds_gateway_and_preserves_virtual_state():
    gateway = Gateway()
    try:
        before = gateway.adapter.read_state().model_dump(exclude={"observed_at"})
        row = gateway.create(NewRequest(command=Command(target_pct=20, duration_s=3600)))
        evaluated = gateway.evaluate(row["id"])
        assert evaluated["status"] == "hold"
        assert evaluated["report"]["reason_code"] == "DEMO_POLICY_OUT_OF_SCOPE"
        assert evaluated["report"]["simulation"] is None
        assert not evaluated["report"]["can_approve"]
        assert gateway.adapter.read_state().model_dump(exclude={"observed_at"}) == before
        assert gateway.adapter.executions == {}
    finally:
        gateway.close()
