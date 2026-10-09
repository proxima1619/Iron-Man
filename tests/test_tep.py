"""Protocol/policy tests; opt-in integration tests execute the real external core."""
import csv
import io
import os
from pathlib import Path
import subprocess
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from backend import main
from backend.contracts import NewRequest, TEPCommand, TEPResult, DecisionReport, RequestRecord, DecisionInput, ExecutionInput, TEPVariable
from backend.gateway.service import Gateway
from backend.simulator.tep import service as tep
from backend.simulator.tep.build import source_lock

def command(**changes):
    return TEPCommand(type="set_tep_cooling_water", variable="XMV10", value=42,
                      duration_s=60, sample_period_s=10, **changes)

def request(cmd=None):
    return NewRequest(equipment_id="tep-sim-01", purpose="TEP integration test", command=cmd or command())

def protocol_bytes():
    # Synthetic CSV for parser rejection tests only, never a process/physics fixture.
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(tep.HEADER)
    for t in range(0, 61, 10):
        u = list(tep.INITIAL_XMV)
        if t:
            u[9] = 42.
        writer.writerow([t, 0, *u, *[0.] * 41, *[0.] * 50])
    return stream.getvalue().encode()

def test_pinned_source_and_variable_units():
    lock = source_lock()
    assert lock["commit"] == "81a7ac9dc04f91bc0898c36f8522372e0e437fc1"
    assert tep.VARIABLES["XMV10"].unit == "percent_full_scale"
    assert tep.VARIABLES["XMEAS7"].unit == "kPa_gauge"
    assert tep.VARIABLES["XMEAS9"].unit == "degC"
    assert tep.VARIABLES["XMEAS21"].name == "Reactor cooling water outlet temperature"
    assert tep.VARIABLES["XMEAS22"].name == "Condenser cooling water outlet temperature"

@pytest.mark.parametrize("mutation", ["header", "missing", "nan", "wrong_mv", "shutdown", "duplicate_time", "wrong_step", "truncated"])
def test_invalid_external_protocol_rejected(mutation):
    rows = list(csv.reader(io.StringIO(protocol_bytes().decode())))
    if mutation == "header": rows[0][22] = "temperature_unit_unknown"
    if mutation == "missing": rows[-1].pop()
    if mutation == "nan": rows[-1][14] = "nan"
    if mutation == "wrong_mv": rows[-1][11] = "80"
    if mutation == "shutdown": rows[-1][1] = "4"
    if mutation == "duplicate_time": rows[-1][0] = "50"
    if mutation == "wrong_step": rows[-1][0] = "65"
    if mutation == "truncated": rows.pop()
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    with pytest.raises(tep.RunFailure, match="TEP") as exc:
        tep.parse_csv(out.getvalue().encode(), command(), 42.)
    assert exc.value.code == "INVALID_OUTPUT"

@pytest.mark.parametrize("value,horizon,sample", [(-1,60,10),(101,60,10),(42,1801,1),(42,61,10)])
def test_unsupported_input_holds_without_external_execution(monkeypatch, value, horizon, sample):
    monkeypatch.setattr(tep, "run_branch", lambda *a: pytest.fail("unsupported input must not execute"))
    cmd = TEPCommand(type="set_tep_cooling_water", variable="XMV10", value=value,
                     duration_s=horizon, sample_period_s=sample)
    gateway = Gateway()
    try:
        row = gateway.evaluate(gateway.create(request(cmd))["id"])
        RequestRecord.model_validate(row)
        assert row["status"] == "hold" and row["report"]["can_approve"] is False
        result = row["report"]["tep_simulation"]
        assert result["status"] == "out_of_domain" and result["baseline"] is None
        assert not result["comparison"]
    finally: gateway.close()

def test_missing_engine_stays_hold_and_does_not_touch_virtual_equipment(monkeypatch, tmp_path):
    monkeypatch.setenv("IRON_MAN_TEP_ENGINE_DIR", str(tmp_path / "missing"))
    gateway = Gateway(tmp_path / "db.sqlite3")
    try:
        state = gateway.adapter.read_state()
        row = gateway.evaluate(gateway.create(request())["id"])
        assert row["status"] == "hold" and row["report"]["simulation"] is None
        assert row["report"]["tep_simulation"]["failure_code"] == "ENGINE_UNAVAILABLE"
        assert not gateway.store.notifications(row["id"])
        assert gateway.adapter.read_state().model_dump(exclude={"observed_at"}) == state.model_dump(exclude={"observed_at"})
        with pytest.raises(HTTPException):
            gateway.decide(row["id"], DecisionInput(decision="approve", reason="test", report_digest=row["report"]["digest"]), "approver")
        with pytest.raises(HTTPException):
            gateway.execute(row["id"], ExecutionInput(report_digest=row["report"]["digest"]))
    finally: gateway.close()
    reopened = Gateway(tmp_path / "db.sqlite3")
    try: RequestRecord.model_validate(reopened.get(row["id"]))
    finally: reopened.close()

def test_unknown_units_hold(monkeypatch):
    definitions = dict(tep.VARIABLES)
    definitions["XMEAS9"] = TEPVariable.model_construct(name="Reactor temperature", unit="unknown")
    monkeypatch.setattr(tep, "VARIABLES", definitions)
    result = tep.simulate(command())
    assert result.status == "failed" and result.failure_code == "UNKNOWN_UNITS"
    assert result.baseline is None

@pytest.mark.parametrize("code", [2, 1, 124])
def test_nonzero_external_exit_never_produces_results(monkeypatch, tmp_path, code):
    monkeypatch.setattr(tep, "launcher", lambda: [])
    monkeypatch.setattr(tep, "engine_path", lambda x: str(x))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, code, protocol_bytes(), b"failure"))
    with pytest.raises(tep.RunFailure):
        tep.run_branch(command(), 42., Path("not-run"), tmp_path / "branch")

def test_branch_timeout_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(tep, "launcher", lambda: [])
    monkeypatch.setattr(tep, "engine_path", lambda x: str(x))
    def fail(*a, **kw): raise subprocess.TimeoutExpired(a, 30)
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(tep.RunFailure) as exc:
        tep.run_branch(command(), 42., Path("not-run"), tmp_path / "branch")
    assert exc.value.code == "RUN_TIMEOUT"

def test_wrong_equipment_and_pump_semantics_rejected():
    with pytest.raises(ValidationError): NewRequest(command=command())
    with pytest.raises(ValidationError): NewRequest(equipment_id="tep-sim-01", command={"target_pct":80})
    with pytest.raises(ValidationError): TEPCommand.model_validate({"type":"set_tep_cooling_water", "variable":"XMV10", "target_pct":80})

REAL = pytest.mark.skipif(os.getenv("IRON_MAN_TEST_TEP") != "1", reason="Set IRON_MAN_TEST_TEP=1 after building the real TE core")

@pytest.fixture(scope="module")
def real_pair():
    result = tep.simulate(command())
    assert result.status == "completed", result.detail
    return result

@REAL
def test_real_repeat_same_initial_state_time_axis_and_changes(real_pair):
    repeated = tep.simulate(command())
    assert repeated == real_pair
    assert [p.time_s for p in real_pair.baseline.points] == list(range(0,61,10))
    assert real_pair.baseline.points[0] == real_pair.candidate.points[0]
    # Original model base case (Downs & Vogel Table 4), not measured field data.
    assert real_pair.baseline.points[0].xmeas[6] == pytest.approx(2705., abs=.001)
    assert real_pair.baseline.points[0].xmeas[8] == pytest.approx(120.4, abs=.001)
    assert real_pair.baseline.points[0].xmeas[20] == pytest.approx(94.599, abs=.001)
    assert real_pair.baseline.points[0].xmeas[21] == pytest.approx(77.297, abs=.001)
    assert len(real_pair.provenance.initial_state) == 50
    assert real_pair.comparison["XMEAS9"].final_delta < 0
    assert all(p.xmv[9] == 42 for p in real_pair.candidate.points[1:])
    assert all(p.xmv[9] == tep.INITIAL_XMV[9] for p in real_pair.baseline.points)
    assert real_pair.field_validation == "not_performed_no_measured_data"
    assert real_pair.data_origin == "simulation"

@REAL
def test_real_unchanged_input_yields_zero_delta():
    cmd = TEPCommand(type="set_tep_cooling_water", variable="XMV10", value=tep.INITIAL_XMV[9], duration_s=60, sample_period_s=10)
    result = tep.simulate(cmd)
    assert result.status == "completed", result.detail
    assert result.baseline == result.candidate
    assert all(m.max_abs_delta == 0 and m.final_delta == 0 for m in result.comparison.values())

@REAL
def test_real_condenser_input_changes_condenser_measurement():
    cmd = TEPCommand(type="set_tep_cooling_water", variable="XMV11", value=19, duration_s=60, sample_period_s=10)
    result = tep.simulate(cmd)
    assert result.status == "completed", result.detail
    assert result.comparison["XMEAS22"].final_delta < 0
    assert all(p.xmv[10] == 19 for p in result.candidate.points[1:])
    assert all(p.xmv[9] == tep.INITIAL_XMV[9] for p in result.candidate.points)

@REAL
def test_real_core_shutdown_has_no_success_metrics():
    cmd = TEPCommand(type="set_tep_cooling_water", variable="XMV10", value=0, duration_s=600, sample_period_s=10)
    result = tep.simulate(cmd)
    assert result.status == "failed" and result.failure_code == "PROCESS_SHUTDOWN", result.detail
    assert result.baseline is None and result.candidate is None and not result.comparison

@REAL
@pytest.mark.parametrize("corruption", ["missing_endpoint", "initial", "unit", "approval", "metric", "wrong_input", "unknown_unit"])
def test_real_result_contract_rejects_missing_or_unsafe_reports(real_pair, corruption):
    result = real_pair.model_dump()
    if corruption == "missing_endpoint": result["candidate"]["points"].pop()
    if corruption == "initial": result["candidate"]["points"][0]["xmeas"][8] += 1
    if corruption == "unit": result["variables"]["XMEAS9"]["unit"] = ""
    if corruption == "unknown_unit": result["variables"]["XMEAS9"]["unit"] = "unknown"
    if corruption == "metric": result["comparison"]["XMEAS9"]["final_delta"] += 10
    if corruption == "wrong_input": result["candidate"]["points"][-1]["xmv"][9] = 80
    if corruption != "approval":
        with pytest.raises(ValidationError): TEPResult.model_validate(result)
    else:
        gateway = Gateway()
        try:
            row, context = gateway._prepare_evaluation(gateway.create(request())["id"])
            from backend.gateway.evaluation import failure_report
            report = failure_report(context, "TEP_POLICY_NOT_CONFIGURED", "test")
            report.update(tep_simulation=result, can_approve=True, verdict="awaiting_approval", digest="test")
            with pytest.raises(ValidationError): DecisionReport.model_validate(report)
        finally: gateway.close()

@REAL
def test_real_async_http_request_persists_hold_and_refuses_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("IRON_MAN_DB_PATH", str(tmp_path / "gateway.sqlite3"))
    monkeypatch.setenv("IRON_MAN_DEPLOYMENT", "local")
    with TestClient(main.app) as client:
        op = {"Authorization":"Bearer local-operator"}
        approver = {"Authorization":"Bearer local-approver"}
        created = client.post("/requests", headers=op, json=request().model_dump())
        assert created.status_code == 201
        key = created.json()["id"]
        response = client.post(f"/requests/{key}/evaluate", headers=op, json={})
        assert response.status_code == 202 and response.json()["status"] == "evaluating"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            row = client.get(f"/requests/{key}", headers=op).json()
            if row["status"] != "evaluating": break
            time.sleep(.05)
        assert row["status"] == "hold", row
        assert row["report"]["tep_simulation"]["status"] == "completed", row
        assert row["report"]["reason_code"] == "TEP_POLICY_NOT_CONFIGURED"
        assert client.post(f"/requests/{key}/decisions", headers=approver,
            json={"decision":"approve","reason":"test","report_digest":row["report"]["digest"]}).status_code == 409
        assert client.post(f"/requests/{key}/execute", headers=op,
            json={"report_digest":row["report"]["digest"]}).status_code == 409
        assert len(client.get(f"/requests/{key}/history", headers=op).json()["reports"]) == 1
