"""V3 virtual clock, persistent plant state and conservative approval checks."""

import json
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import main
from backend.contracts import Command, DecisionInput, ExecutionInput, NewRequest, Scenario
from backend.gateway.service import Gateway, state_digest
from backend.gateway.storage import SQLiteStore
from backend.simulator import adapter as adapter_module
from backend.simulator import service as simulator
from backend.simulator.adapter import DemoAdapter
from backend.simulator.model import MODEL, advance_state
from tests.test_gateway import APP, OP


@pytest.fixture
def plant():
    store = SQLiteStore()
    try:
        yield DemoAdapter(store)
    finally:
        store.close()


def test_applying_setpoint_keeps_actual_state_until_virtual_time_advances(plant):
    before = plant.read_state()
    result = plant.apply_command("setpoint", Command(target_pct=80, duration_s=10))
    applied = plant.read_state()
    assert result["status"] == "applied" and result["virtual"] is True
    assert applied.target_pump_speed_pct == 80
    assert applied.pump_speed_pct == before.pump_speed_pct == 100
    assert applied.temperature_c == before.temperature_c == 60
    assert applied.simulation_time_s == before.simulation_time_s == 0
    assert applied.revision == before.revision + 1

    plant.advance_time(30)
    advanced = plant.read_state()
    assert 80 < advanced.pump_speed_pct < 100
    assert advanced.temperature_c > 60
    assert advanced.simulation_time_s == 30
    # duration_s is the evaluation horizon, not an automatic setpoint rollback.
    assert advanced.target_pump_speed_pct == 80
    assert advanced.revision == applied.revision + 1


def test_evolution_uses_same_heat_balance_and_retains_state_across_actions(plant):
    plant.apply_command("ramp", Command(target_pct=60))
    expected_temperature, expected_speed = 60.0, 100.0
    for _ in range(60):
        expected_temperature, expected_speed = advance_state(
            expected_temperature, expected_speed, 60, 1, 1, 1)

    plant.advance_time(25)
    halfway = plant.read_state()
    plant.advance_time(35)
    final = plant.read_state()
    assert final.temperature_c == pytest.approx(expected_temperature, abs=1e-10)
    assert final.pump_speed_pct == pytest.approx(expected_speed, abs=1e-10)
    assert final.simulation_time_s == 60
    assert final.temperature_c > halfway.temperature_c > 60
    assert 60 < final.pump_speed_pct < halfway.pump_speed_pct < 100

    plant.reset_state()
    plant.apply_command("single-ramp", Command(target_pct=60))
    plant.advance_time(60)
    single = plant.read_state()
    assert single.temperature_c == pytest.approx(final.temperature_c, abs=1e-10)
    assert single.pump_speed_pct == pytest.approx(final.pump_speed_pct, abs=1e-10)


def test_reading_and_restart_leave_clock_and_observation_paused(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter_module.time, "time", lambda: 1700000000.0)
    path = tmp_path / "paused.sqlite3"
    store = SQLiteStore(path)
    plant = DemoAdapter(store)
    plant.apply_command("paused-command", Command(target_pct=80))
    plant.advance_time(40)
    before = plant.read_state()
    store.close()

    monkeypatch.setattr(adapter_module.time, "time", lambda: 1700003600.0)
    store = SQLiteStore(path)
    try:
        restarted = DemoAdapter(store)
        assert restarted.read_state() == before
        assert restarted.read_state() == before
        assert restarted.get_execution("paused-command") is not None
    finally:
        store.close()


def test_sampling_refreshes_only_observation_and_preserves_approval_context(plant, monkeypatch):
    before = plant.read_state()
    monkeypatch.setattr(adapter_module.time, "time", lambda: before.observed_at + 120)
    plant.sample_state()
    after = plant.read_state()
    assert after.observed_at == before.observed_at + 120
    assert after.model_dump(exclude={"observed_at"}) == before.model_dump(exclude={"observed_at"})
    assert state_digest(after) == state_digest(before)


def test_receipt_retry_does_not_reset_target_or_rewind_evolved_state(plant):
    command = Command(target_pct=80)
    original = plant.apply_command("once", command)
    plant.advance_time(30)
    evolved = plant.read_state()
    assert plant.apply_command("once", command) == original
    assert plant.read_state() == evolved
    assert len(plant.executions) == 1
    with pytest.raises(ValueError):
        plant.apply_command("once", Command(target_pct=60))
    assert plant.read_state() == evolved


def test_baseline_retains_existing_target_during_an_unfinished_ramp(plant):
    plant.apply_command("ongoing", Command(target_pct=60))
    plant.advance_time(10)
    current = plant.read_state()
    assert 60 < current.pump_speed_pct < 100
    command = Command(target_pct=80, duration_s=300)
    before = plant.read_state()
    result = simulator.simulate(command, current, [Scenario(kind="normal")])
    expected_baseline = simulator._run(current, 60, 300, 1)["peak_c"]
    frozen_actual_baseline = simulator._run(current, current.pump_speed_pct, 300, 1)["peak_c"]
    expected_candidate = simulator._run(current, 80, 300, 1)["peak_c"]
    assert result.status == "completed"
    assert result.scenarios[0].baseline_peak_c == pytest.approx(expected_baseline)
    assert result.scenarios[0].baseline_peak_c > frozen_actual_baseline
    assert result.scenarios[0].candidate_peak_c == pytest.approx(expected_candidate)
    assert plant.read_state() == before  # What-if calculations never mutate the plant.


def test_domain_exit_is_sticky_until_explicit_reset_and_keeps_receipts(plant):
    plant.apply_command("no-cooling", Command(target_pct=0))
    plant.advance_time(3600)
    unsupported = plant.read_state()
    assert unsupported.domain_status == "out_of_domain"
    assert unsupported.sensor_quality == "invalid"
    assert unsupported.domain_reason
    assert MODEL.temperature_min_c <= unsupported.temperature_c <= MODEL.temperature_max_c
    assert 0 < unsupported.simulation_time_s < 3600
    assert unsupported.target_pump_speed_pct == 0
    with pytest.raises(ValueError):
        plant.advance_time(1)
    assert plant.read_state() == unsupported

    plant.sample_state()
    plant.update_demo_state(1, "valid")
    assert plant.read_state().domain_status == "out_of_domain"
    assert plant.read_state().sensor_quality == "invalid"
    result = simulator.simulate(Command(target_pct=100), plant.read_state(), [Scenario(kind="normal")])
    assert result.status == "out_of_domain" and result.scenarios == []

    revision = plant.read_state().revision
    receipts = plant.executions
    plant.reset_state()
    reset = plant.read_state()
    assert reset.revision == revision + 1
    assert reset.temperature_c == 60
    assert reset.pump_speed_pct == reset.target_pump_speed_pct == 100
    assert reset.load_ratio == 1 and reset.simulation_time_s == 0
    assert reset.sensor_quality == "valid" and reset.domain_status == "ready"
    assert reset.domain_reason is None
    assert plant.executions == receipts
    plant.advance_time(10)
    assert plant.read_state().simulation_time_s == 10


def test_schema_v1_migration_preserves_history_and_setpoint(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    old_state = {"revision": 7, "load_ratio": 0.8, "pump_speed_pct": 42.0,
                 "sensor_quality": "valid"}
    request = {"id": "legacy-request", "historical_payload": "unchanged"}
    report = {"digest": "legacy-digest", "model_version": "cooling-demo-v2"}
    approval = {"report_digest": "legacy-digest", "actor": "old-approver"}
    receipt = {"execution_id": "legacy-execution", "command": {"target_pct": 42},
               "status": "applied", "virtual": True}
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE requests (id TEXT PRIMARY KEY, record_json TEXT NOT NULL)")
        db.execute("CREATE TABLE reports (request_id TEXT NOT NULL REFERENCES requests(id), "
                   "digest TEXT NOT NULL, report_json TEXT NOT NULL, PRIMARY KEY(request_id,digest))")
        db.execute("CREATE TABLE approvals (request_id TEXT NOT NULL REFERENCES requests(id), "
                   "report_digest TEXT NOT NULL, approval_json TEXT NOT NULL, PRIMARY KEY(request_id,report_digest))")
        db.execute("CREATE TABLE demo_state (id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL)")
        db.execute("CREATE TABLE adapter_executions (id TEXT PRIMARY KEY, result_json TEXT NOT NULL)")
        db.execute("INSERT INTO requests VALUES (?, ?)", (request["id"], json.dumps(request)))
        db.execute("INSERT INTO reports VALUES (?, ?, ?)", (request["id"], report["digest"], json.dumps(report)))
        db.execute("INSERT INTO approvals VALUES (?, ?, ?)", (request["id"], report["digest"], json.dumps(approval)))
        db.execute("INSERT INTO demo_state VALUES (1, ?)", (json.dumps(old_state),))
        db.execute("INSERT INTO adapter_executions VALUES (?, ?)", (receipt["execution_id"], json.dumps(receipt)))
        db.execute("PRAGMA user_version=1")

    store = SQLiteStore(path)
    try:
        state = DemoAdapter(store).read_state()
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert state.revision == old_state["revision"] + 1 and state.load_ratio == 0.8
        assert state.pump_speed_pct == state.target_pump_speed_pct == 42
        assert state.temperature_c == 60 and state.simulation_time_s == 0
        assert state.model_version == MODEL.version == "cooling-demo-v3"
        assert state.domain_status == "ready" and state.observed_at > 0
        assert store.get(request["id"]) == request
        assert store.history(request["id"]) == {"reports": [report], "approvals": [approval]}
        assert store.get_execution(receipt["execution_id"]) == receipt
    finally:
        store.close()


def test_clock_advance_invalidates_approval_before_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "fixture")
    calculation = simulator.simulate
    monkeypatch.setattr(simulator, "simulate", lambda *args: calculation(*args).model_copy(update={"mock": True}))
    gateway = Gateway(tmp_path / "approval.sqlite3")
    try:
        row = gateway.create(NewRequest(command=Command(target_pct=80)))
        row = gateway.evaluate(row["id"])
        assert row["status"] == "awaiting_approval"
        row = gateway.decide(row["id"], DecisionInput(report_digest=row["report"]["digest"],
            decision="approve", reason="test-only policy"), "approver")
        gateway.adapter.advance_time(10)
        with pytest.raises(HTTPException) as error:
            gateway.execute(row["id"], ExecutionInput(report_digest=row["report"]["digest"]))
        assert error.value.status_code == 409
        assert gateway.get(row["id"])["status"] == "revalidation_required"
        assert not gateway.adapter.executions
    finally:
        gateway.close()


def test_paused_observation_stays_stale_until_explicit_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "fixture")
    monkeypatch.setattr(adapter_module.time, "time", lambda: 1700000000.0)
    gateway = Gateway(tmp_path / "stale-observation.sqlite3")
    try:
        row = gateway.create(NewRequest(command=Command(target_pct=80)))
        initial = gateway.adapter.read_state()
        monkeypatch.setattr(adapter_module.time, "time", lambda: 1700000061.0)
        assert gateway.adapter.read_state() == initial
        stale = gateway.evaluate(row["id"])
        assert stale["status"] == "hold"
        assert stale["report"]["reason_code"] == "INVALID_STATE"
        gateway.adapter.sample_state()
        refreshed = gateway.evaluate(row["id"])
        assert refreshed["report"]["snapshot"]["observed_at"] == 1700000061.0
        assert refreshed["status"] == "hold"
        assert refreshed["report"]["reason_code"] == "LIVE_POLICY_NOT_CONFIGURED"
        assert gateway.adapter.read_state().simulation_time_s == 0
        assert not gateway.adapter.executions
    finally:
        gateway.close()


@pytest.fixture
def plant_client(tmp_path, monkeypatch):
    monkeypatch.setenv("IRON_MAN_OPERATOR_TOKEN", "local-operator")
    monkeypatch.setenv("IRON_MAN_APPROVER_TOKEN", "local-approver")
    gateway = Gateway(tmp_path / "api-plant.sqlite3")
    monkeypatch.setattr(main, "gateway", gateway)
    try:
        yield TestClient(main.app)
    finally:
        gateway.close()


@pytest.mark.parametrize("route", ["advance", "sample", "reset"])
def test_virtual_clock_actions_require_approver_role(plant_client, route):
    body = {"seconds_s": 10} if route == "advance" else None
    assert plant_client.post(f"/demo/{route}", json=body).status_code == 401
    assert plant_client.post(f"/demo/{route}", headers=OP, json=body).status_code == 403
    assert plant_client.post(f"/demo/{route}", headers=APP, json=body).status_code == 200


@pytest.mark.parametrize("seconds", [0, -1, 3601, 1.5, True, "10"])
def test_advance_api_rejects_invalid_time_without_changing_state(plant_client, seconds):
    before = plant_client.get("/state", headers=OP).json()
    response = plant_client.post("/demo/advance", headers=APP, json={"seconds_s": seconds})
    assert response.status_code == 422
    assert plant_client.get("/state", headers=OP).json() == before


def test_advance_api_returns_persisted_virtual_clock(plant_client):
    response = plant_client.post("/demo/advance", headers=APP, json={"seconds_s": 10})
    assert response.status_code == 200
    state = response.json()
    assert state["simulation_time_s"] == 10
    assert state["model_version"] == "cooling-demo-v3"
    assert state["target_pump_speed_pct"] == state["pump_speed_pct"] == 100
    assert plant_client.get("/state", headers=OP).json() == state


def test_async_evaluation_cannot_publish_after_virtual_time_advances(tmp_path, monkeypatch):
    from tests.test_async_evaluation import gated_worker, wait_for, finished

    monkeypatch.setenv("IRON_MAN_OPERATOR_TOKEN", "local-operator")
    monkeypatch.setenv("IRON_MAN_APPROVER_TOKEN", "local-approver")
    monkeypatch.setenv("IRON_MAN_EVIDENCE_MODE", "fixture")
    gate = tmp_path / "virtual-clock-gate"
    gate.mkdir()
    gateway = Gateway(tmp_path / "async-clock.sqlite3", worker_target=gated_worker)
    monkeypatch.setattr(main, "gateway", gateway)
    try:
        # Capture a plant while its actual pump is still following an earlier target.
        gateway.adapter.apply_command("earlier-target", Command(target_pct=80))
        gateway.adapter.advance_time(10)
        captured = gateway.adapter.read_state()
        receipts = gateway.adapter.executions
        client = TestClient(main.app)
        row = client.post("/requests", headers=OP,
            json={"command": {"target_pct": 90}, "purpose": str(gate)}).json()
        started = client.post(f'/requests/{row["id"]}/evaluate', headers=OP, json={})
        assert started.status_code == 202
        wait_for(lambda: (gate / "started").exists())
        context = dict(next(iter(gateway.evaluations.jobs.values())).context)
        assert context["snapshot"] == captured.model_dump()
        assert context["snapshot"]["target_pump_speed_pct"] == 80
        assert context["snapshot"]["simulation_time_s"] == 10
        assert context["snapshot"]["model_version"] == "cooling-demo-v3"

        advanced = client.post("/demo/advance", headers=APP, json={"seconds_s": 10})
        assert advanced.status_code == 200
        assert advanced.json()["simulation_time_s"] == 20
        assert advanced.json()["temperature_c"] > captured.temperature_c
        assert 80 < advanced.json()["pump_speed_pct"] < captured.pump_speed_pct
        assert gateway.get(row["id"])["status"] == "evaluating"
        (gate / "release").touch()
        final = wait_for(lambda: finished(gateway, row["id"]))
        assert final["status"] == "hold"
        assert final["evaluation"]["status"] == "completed"
        assert final["report"]["reason_code"] == "EVALUATION_CONTEXT_CHANGED"
        assert final["report"]["can_approve"] is False
        assert final["report"]["snapshot"] == captured.model_dump()
        assert final["approval"] is None
        assert gateway.adapter.executions == receipts
    finally:
        gateway.close()
