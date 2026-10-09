"""Pure evaluation worker: receives immutable inputs, never opens the gateway DB."""
import hashlib
import json
import time
from backend.contracts import NewRequest, Snapshot, Scenario, SimulationResult, EvidenceReview
from backend.evidence import service as evidence
from backend.simulator import service as simulator

SNAPSHOT_TTL_S = 60

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def state_digest(snapshot):
    return digest(snapshot.model_dump(exclude={"observed_at"}))

def calculate(context):
    body = NewRequest.model_validate(context["request"])
    snapshot = Snapshot.model_validate(context["snapshot"])
    report = {"schema_version": "1.0", "revision": context["revision"], "command_digest": digest(body.command.model_dump()),
        "snapshot": snapshot.model_dump(), "snapshot_digest": state_digest(snapshot),
        "model_version": context["model_version"], "policy_version": context["policy_version"],
        "mock": True, "can_approve": False, "evidence": None, "simulation": None}
    try:
        if (snapshot.domain_status != "ready" or snapshot.sensor_quality != "valid"
                or time.time() - snapshot.observed_at > SNAPSHOT_TTL_S):
            report.update(verdict="hold", reason_code="INVALID_STATE", reason="센서 품질 또는 상태 유효 시간을 확인하세요.")
        elif body.command.target_pct < 20:
            report.update(verdict="blocked", reason_code="POLICY_VIOLATION", reason="데모 정책의 최소 속도 20% 미만입니다.")
        else:
            review = EvidenceReview.model_validate(evidence.review_evidence(body, snapshot))
            report["evidence"] = review.model_dump()
            report["mock"] = review.mock
            scenarios = [Scenario(kind="normal")]
            seen = {"normal"}
            for candidate in review.proposed_tests[:3]:
                validated = Scenario.model_validate(candidate)
                if validated.kind not in seen:
                    scenarios.append(validated)
                    seen.add(validated.kind)
            if review.status in {"insufficient", "failed"} or (
                not review.mock and any(c.applicability != "applicable" or c.missing_conditions for c in review.cards)
            ):
                report.update(verdict="hold", reason_code="EVIDENCE_INCOMPLETE",
                              reason="필수 근거 또는 적용 조건 검토가 완료되지 않았습니다.")
            else:
                result = SimulationResult.model_validate(
                    simulator.simulate(body.command, snapshot, scenarios))
                report["simulation"] = result.model_dump()
                report["mock"] = review.mock or result.mock
                if result.model_version != context["model_version"]:
                    raise ValueError("simulation model version mismatch")
                if result.status != "completed":
                    report.update(verdict="hold", reason_code="SIMULATION_INCOMPLETE",
                                  reason="모델 범위 밖이거나 계산을 완료하지 못했습니다.")
                else:
                    expected = {(s.kind, s.evidence_id) for s in scenarios}
                    actual = {(s.kind, s.evidence_id) for s in result.scenarios}
                    if actual != expected:
                        raise ValueError("missing or unexpected scenario result")
                    unsafe = any(s.exceeded for s in result.scenarios)
                    if unsafe:
                        report.update(verdict="blocked", reason_code="LIMIT_EXCEEDED",
                                      reason="시험 결과가 온도 한계를 초과했습니다.")
                    elif not (review.mock and result.mock):
                        # Real modules require an explicit policy before approval is enabled.
                        report.update(verdict="hold", reason_code="LIVE_POLICY_NOT_CONFIGURED",
                                      reason="실제 모듈 승인 정책이 아직 구성되지 않았습니다.")
                    else:
                        report.update(verdict="awaiting_approval", reason_code="DEMO_PASS",
                                      can_approve=True, reason="모의 시험 통과: 가상 설비 승인 가능")
    except Exception:
        report.update(verdict="hold", reason_code="MODULE_FAILURE", reason="검토 모듈 실패: 실행을 보류합니다.")
    return report

def failure_report(context, code, reason):
    return {"schema_version": "1.0", "revision": context["revision"],
        "command_digest": digest(context["request"]["command"]),
        "snapshot": context["snapshot"], "snapshot_digest": state_digest(Snapshot.model_validate(context["snapshot"])),
        "model_version": context["model_version"], "policy_version": context["policy_version"],
        "mock": True, "can_approve": False, "evidence": None, "simulation": None,
        "verdict": "hold", "reason_code": code, "reason": reason}

def process_worker(context, output):
    try:
        output.send(calculate(context))
    finally:
        output.close()
