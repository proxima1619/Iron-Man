"""Shared HTTP checks for the real TEP engine; successful calculations stay on hold.

The caller supplies an authenticated request function returning (status, JSON).
No field-safety thresholds or approval exceptions are introduced by this check.
"""
import time


def run(request, operator, approver):
    status, before = request("/state", token=operator)
    assert status == 200
    before.pop("observed_at")
    records = []
    for variable, value, expected in (
        ("XMV10", 42, "completed"), ("XMV11", 19, "completed"),
        ("XMV10", 0, "failed"), ("XMV10", 101, "out_of_domain"),
    ):
        status, row = request("/requests", token=operator, body={
            "equipment_id": "tep-sim-01", "purpose": "TEP deployment integration check",
            "command": {"type": "set_tep_cooling_water", "variable": variable,
                        "value": value, "duration_s": 600, "sample_period_s": 10},
        })
        assert status == 201
        path = f'/requests/{row["id"]}'
        status, pending = request(path + "/evaluate", token=operator, body={})
        assert status == 202 and pending["status"] == "evaluating"
        # State reads remain available while an evaluation is scheduled.
        assert request("/state", token=operator)[0] == 200
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            status, row = request(path, token=operator)
            assert status == 200
            if row["status"] != "evaluating":
                break
            time.sleep(.2)
        report = row["report"]
        result = report["tep_simulation"]
        assert row["status"] == "hold" and result["status"] == expected
        assert report["can_approve"] is False and report["execution_scope"] == "unconfigured"
        assert report["simulation"] is None and report["evidence"] is None and report["assessment"] is None
        assert report["snapshot"]["profile"] == "nist-teinit-base-case-v1"
        assert "temperature_c" not in report["snapshot"]
        assert result["data_origin"] == "simulation"
        assert result["field_validation"] == "not_performed_no_measured_data"
        assert result["configuration"]["variable"] == variable
        assert result["configuration"]["candidate_value"] == value
        assert result["variables"][variable]["unit"] == "percent_full_scale"
        if expected == "completed":
            assert report["reason_code"] == "TEP_POLICY_NOT_CONFIGURED"
            assert result["provenance"]["source_commit"] == "81a7ac9dc04f91bc0898c36f8522372e0e437fc1"
            assert len(result["provenance"]["binary_sha256"]) == 64
            assert len(result["provenance"]["initial_state"]) == 50
            assert len(result["baseline"]["points"]) == len(result["candidate"]["points"]) == 61
            assert result["baseline"]["points"][0] == result["candidate"]["points"][0]
            assert len(result["comparison"]) == 41
            measured = "XMEAS9" if variable == "XMV10" else "XMEAS22"
            assert result["comparison"][measured]["final_delta"] < 0
        else:
            assert report["reason_code"] == "SIMULATION_INCOMPLETE"
            assert result["failure_code"] == ("PROCESS_SHUTDOWN" if expected == "failed" else "UNSUPPORTED_INPUT")
            assert result["baseline"] is None and result["candidate"] is None and not result["comparison"]
        assert request(path + "/decisions", token=approver, body={
            "decision": "approve", "reason": "TEP approval must remain disabled",
            "report_digest": report["digest"],
        })[0] == 409
        assert request(path + "/execute", token=operator, body={"report_digest": report["digest"]})[0] == 409
        status, history = request(path + "/history", token=operator)
        assert status == 200 and history["reports"]
        assert request(path + "/notifications", token=approver) == (200, [])
        records.append(row)
    status, after = request("/state", token=operator)
    assert status == 200
    after.pop("observed_at")
    assert before == after, "TEP tests must not modify the cooling-tank state"
    print("PASS: real TEP XMV10/XMV11 HTTP results, shutdown/unsupported holds, provenance, units, approval/execution denial")
    return records
