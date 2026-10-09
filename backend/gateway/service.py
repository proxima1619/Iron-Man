"""Owner 1: demo orchestration and authorization. In-memory, single worker only."""
import hashlib
import json
import threading
import time
import uuid
from fastapi import HTTPException
from backend.contracts import NewRequest, Scenario
from backend.evidence import service as evidence
from backend.simulator import service as simulator
from backend.simulator.adapter import DemoAdapter

POLICY_VERSION = "demo-policy-v1"
APPROVAL_TTL_S = 300
SNAPSHOT_TTL_S = 60

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def state_digest(snapshot):
    return digest(snapshot.model_dump(exclude={"observed_at"}))

class Gateway:
    def __init__(self):
        self.lock = threading.RLock()
        self.adapter = DemoAdapter()
        self.requests = {}

    def get(self, request_id):
        if request_id not in self.requests:
            raise HTTPException(404, "요청을 찾을 수 없습니다.")
        return self.requests[request_id]

    def event(self, row, kind, **data):
        row["events"].append({"kind": kind, "at": time.time(), **data})

    def create(self, body: NewRequest):
        with self.lock:
            row = {"id": str(uuid.uuid4()), "revision": 1, "request": body.model_dump(),
                   "status": "draft", "report": None, "approval": None,
                   "execution": None, "events": []}
            self.event(row, "created")
            self.requests[row["id"]] = row
            return row

    def evaluate(self, request_id):
        with self.lock:
            row = self.get(request_id)
            if row["status"] in {"executing", "completed", "execution_unknown"}:
                raise HTTPException(409, "이미 실행한 요청입니다. 새 요청을 생성하세요.")
            row["approval"] = None
            row["status"] = "evaluating"
            row["revision"] += 1
            body = NewRequest.model_validate(row["request"])
            snapshot = self.adapter.read_state()
            report = {"revision": row["revision"], "command_digest": digest(body.command.model_dump()),
                "snapshot": snapshot.model_dump(), "snapshot_digest": state_digest(snapshot),
                "model_version": simulator.MODEL_VERSION, "policy_version": POLICY_VERSION,
                "mock": True, "can_approve": False, "evidence": None, "simulation": None}
            try:
                if snapshot.sensor_quality != "valid" or time.time() - snapshot.observed_at > SNAPSHOT_TTL_S:
                    report.update(verdict="hold", reason="센서 품질 또는 상태 유효 시간을 확인하세요.")
                elif body.command.target_pct < 20:
                    report.update(verdict="blocked", reason="데모 정책의 최소 속도 20% 미만입니다.")
                else:
                    review = evidence.review_evidence(body, snapshot)
                    scenarios = [Scenario(kind="normal")]
                    seen = {"normal"}
                    for candidate in review.proposed_tests[:3]:
                        validated = Scenario.model_validate(candidate)
                        if validated.kind not in seen:
                            scenarios.append(validated)
                            seen.add(validated.kind)
                    result = simulator.simulate(body.command, snapshot, scenarios)
                    unsafe = any(s["exceeded"] for s in result.scenarios)
                    report.update(evidence=review.model_dump(), simulation=result.model_dump(),
                        verdict="blocked" if unsafe else "awaiting_approval", can_approve=not unsafe,
                        reason="모의 위험 시험: 요청 차단" if unsafe else "모의 시험 통과: 가상 설비 승인 가능")
            except Exception:
                report.update(verdict="hold", reason="검토 모듈 실패: 실행을 보류합니다.")
                self.event(row, "evaluation_failed")
            report["digest"] = digest(report)
            row["report"] = report
            row["status"] = report["verdict"]
            self.event(row, "evaluated", verdict=row["status"], report_digest=report["digest"])
            return row

    def decide(self, request_id, body, actor):
        with self.lock:
            row = self.get(request_id)
            report = row["report"]
            if not report or row["status"] != "awaiting_approval" or body.report_digest != report["digest"]:
                raise HTTPException(409, "승인 가능한 최신 보고서가 아닙니다.")
            if body.decision == "reject":
                row["status"] = "rejected"
            else:
                row["approval"] = {"actor": actor, "report_digest": report["digest"],
                    "expires_at": time.time() + APPROVAL_TTL_S, "reason": body.reason}
                row["status"] = "approved"
            self.event(row, body.decision, actor=actor, reason=body.reason)
            return row

    def execute(self, request_id, body):
        with self.lock:
            row = self.get(request_id)
            approval, report = row["approval"], row["report"]
            if not approval or not report or body.report_digest != report["digest"]:
                raise HTTPException(409, "유효한 승인이 필요합니다.")
            # Retrying an already completed execution returns the prior result; no reapplication.
            if row["status"] == "completed":
                return row
            if row["status"] != "approved":
                raise HTTPException(409, "현재 상태에서는 실행할 수 없습니다.")
            current = self.adapter.read_state()
            command = NewRequest.model_validate(row["request"]).command
            valid = (approval["expires_at"] > time.time()
                and approval["report_digest"] == report["digest"]
                and digest({k: v for k, v in report.items() if k != "digest"}) == report["digest"]
                and digest(command.model_dump()) == report["command_digest"]
                and state_digest(current) == report["snapshot_digest"]
                and current.sensor_quality == "valid"
                and time.time() - current.observed_at <= SNAPSHOT_TTL_S
                and simulator.MODEL_VERSION == report["model_version"]
                and POLICY_VERSION == report["policy_version"])
            if not valid:
                row["status"] = "revalidation_required"
                row["approval"] = None
                self.event(row, "execution_denied", reason="승인 만료 또는 검증 대상 변경")
                raise HTTPException(409, "승인 만료 또는 검증 대상 변경: 재검증이 필요합니다.")
            execution_id = str(uuid.uuid4())
            row["status"] = "executing"
            self.event(row, "execution_reserved", execution_id=execution_id)
            try:
                result = self.adapter.apply_command(execution_id, command)
                if result.get("status") != "applied":
                    raise RuntimeError("Unconfirmed adapter result")
                row["execution"] = result
                row["status"] = "completed"
                self.event(row, "executed", execution_id=execution_id)
            except Exception:
                row["execution"] = {"execution_id": execution_id, "status": "unknown"}
                row["status"] = "execution_unknown"
                self.event(row, "execution_unknown", execution_id=execution_id)
            return row
