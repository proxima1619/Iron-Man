"""Owner 1: demo orchestration and authorization. SQLite, single worker only."""
import time
import uuid
from fastapi import HTTPException
from backend.contracts import NewRequest, DecisionReport, Snapshot, TEPCommand, TEPResult, EvidenceReview, SimulationResult
from backend.simulator import service as simulator
from backend.simulator.tep import service as tep
from backend.simulator.adapter import DemoAdapter
from backend.gateway.storage import SQLiteStore
from backend.gateway import review as review_policy, notifications

from backend.gateway.policy import POLICY_VERSION, scope_issue, evidence_issue, simulation_issue, physical_risk, coverage_issue, LIMIT_C
APPROVAL_TTL_S = 300
SNAPSHOT_TTL_S = 60

from backend.gateway.evaluation import calculate, digest, failure_report, state_digest
from backend.gateway.jobs import EvaluationRunner

class Gateway:
    def __init__(self, db_path=":memory:", *, max_evaluations=2, evaluation_timeout_s=90, worker_target=None):
        self.store = SQLiteStore(db_path)
        self.lock = self.store.lock
        self.adapter = DemoAdapter(self.store)
        try:
            self.evaluations = EvaluationRunner(self, max_evaluations, evaluation_timeout_s, worker_target)
            self._recover_interrupted()
        except BaseException:
            self.store.close()
            raise

    def close(self):
        try:
            self.evaluations.close()
        finally:
            self.store.close()

    def _recover_interrupted(self):
        for row in self.store.list_records():
            if row["status"] == "evaluating":
                row.update(status="hold", report=None, approval=None)
                if row.get("evaluation"):
                    row["evaluation"].update(status="interrupted", finished_at=time.time())
                self.event(row, "evaluation_interrupted", reason="서버 재시작: 평가를 다시 실행하세요.")
                self.store.save(row)
            elif row["status"] == "executing":
                row["status"] = "execution_unknown"
                self.event(row, "execution_interrupted", reason="서버 재시작: 자동 재실행하지 않습니다.")
                self.store.save(row)

        for note in self.store.notifications():
            if note["status"] == "sending":
                note.update(status="unknown", detail="발송 중 서버 종료: 수신 여부를 확인하세요. 자동 재발송하지 않습니다.")
                row = self.get(note["request_id"])
                self.event(row, "notification_unknown", reason=note["detail"])
                self.store.save(row, notification=note)


    def get(self, request_id):
        row = self.store.get(request_id)
        if row is None:
            raise HTTPException(404, "요청을 찾을 수 없습니다.")
        return row

    def list_records(self):
        return self.store.list_records()

    def history(self, request_id):
        self.get(request_id)
        return self.store.history(request_id)

    def event(self, row, kind, **data):
        row["events"].append({"kind": kind, "at": time.time(), **data})

    def create(self, body: NewRequest):
        with self.lock:
            row = {"id": str(uuid.uuid4()), "revision": 1, "request": body.model_dump(),
                   "status": "draft", "report": None, "approval": None,
                   "execution": None, "evaluation": None, "events": []}
            self.event(row, "created")
            self.store.save(row, contact=body.requester_contact)
            return row

    def _prepare_evaluation(self, request_id, task=None):
        with self.lock:
            row = self.get(request_id)
            if row["status"] == "evaluating":
                raise HTTPException(409, "이 요청은 이미 평가 중입니다.")
            if row["status"] in {"executing", "completed", "execution_unknown"}:
                raise HTTPException(409, "이미 실행한 요청입니다. 새 요청을 생성하세요.")
            body = NewRequest.model_validate(row["request"])
            is_tep = isinstance(body.command, TEPCommand)
            snapshot = tep.snapshot(time.time()) if is_tep else self.adapter.read_state()
            row.update(status="evaluating", approval=None, report=None, revision=row["revision"] + 1,
                       evaluation=task)
            if task:
                task["revision"] = row["revision"]
                self.event(row, "evaluation_started", reason="별도 프로세스에서 검토 중입니다.")
            self.store.save(row)
            return row, {"request_id": row["id"], "revision": row["revision"],
                "request": body.model_dump(), "snapshot": snapshot.model_dump(),
                "model_version": tep.MODEL_VERSION if is_tep else simulator.MODEL_VERSION,
                "policy_version": tep.POLICY_VERSION if is_tep else POLICY_VERSION,
                "execution_scope": "virtual" if not is_tep and type(self.adapter) is DemoAdapter else "unconfigured",
                "review_settings": review_policy.settings(),
                "task_id": task["id"] if task else None}

    def _finish_evaluation(self, context, report, task_status="completed"):
        with self.lock:
            row = self.get(context["request_id"])
            task = row.get("evaluation")
            if (row["status"] != "evaluating" or row["revision"] != context["revision"]
                or (task["id"] if task else None) != context["task_id"]
                or digest(row["request"]) != digest(context["request"])):
                return row  # Late or superseded result must never overwrite newer state.
            if task_status == "completed" and task and time.time() >= task["deadline_at"]:
                task_status = "timed_out"
                report = failure_report(context, "EVALUATION_TIMEOUT", "평가 제한 시간을 초과했습니다.")
            if task_status == "completed":
                expected = failure_report(context, "WORKER_FAILURE", "")
                for key in ("revision", "command_digest", "snapshot", "snapshot_digest", "model_version", "policy_version", "execution_scope"):
                    if report.get(key) != expected[key]:
                        raise ValueError("Evaluation report does not match captured input")
                is_tep = context["request"]["command"]["type"] == "set_tep_cooling_water"
                if is_tep:
                    current = tep.snapshot(context["snapshot"]["configured_at"])
                    if (current.model_dump() != context["snapshot"] or tep.MODEL_VERSION != context["model_version"]
                        or tep.POLICY_VERSION != context["policy_version"]):
                        report = failure_report(context, "EVALUATION_CONTEXT_CHANGED", "TEP 초기화 프로필·모델·정책이 변경되었습니다.")
                    elif report.get("tep_simulation") is not None:
                        result = TEPResult.model_validate(report["tep_simulation"])
                        command = TEPCommand.model_validate(context["request"]["command"])
                        if (result.configuration != tep.configuration(command) or result.model_version != context["model_version"]
                            or (result.status == "completed" and result.variables != tep.VARIABLES)):
                            raise ValueError("TEP result does not match captured inputs/variable definitions")
                else:
                    report = self._finish_cooling_context(context, report)
                if report["reason_code"] == "MODULE_FAILURE":
                    task_status = "failed"
            report = dict(report)
            report["digest"] = digest(report)
            DecisionReport.model_validate(report)
            row.update(report=report, status=report["verdict"])
            if task:
                task.update(status=task_status, finished_at=time.time())
            if task_status != "completed":
                self.event(row, "evaluation_failed", reason=report["reason"])
            self.event(row, "evaluated", verdict=row["status"], report_digest=report["digest"])
            note = None
            if row["status"] == "awaiting_approval":
                note = notifications.queued(row["id"], report["digest"])
                self.event(row, "notification_queued", reason=note["detail"])
            self.store.save(row, notification=note)
            return row

    def _finish_cooling_context(self, context, report):
        current = self.adapter.read_state()
        # An observation already rejected as stale stays INVALID_STATE.
        # Every approval-capable result must still pass finish-time freshness.
        invalid_input_hold = (report.get("reason_code") == "INVALID_STATE"
            and report.get("verdict") == "hold" and report.get("can_approve") is False)
        if (state_digest(current) != state_digest(Snapshot.model_validate(context["snapshot"]))
            or (time.time() - context["snapshot"]["observed_at"] > SNAPSHOT_TTL_S and not invalid_input_hold)
            or simulator.MODEL_VERSION != context["model_version"]
            or POLICY_VERSION != context["policy_version"]
            or review_policy.settings() != tuple(context.get("review_settings", review_policy.settings()))
            or type(self.adapter) is not DemoAdapter):
            report = failure_report(context, "EVALUATION_CONTEXT_CHANGED",
                "검토 중 설비 상태·버전 또는 상태 유효 시간이 달라졌습니다. 다시 검증하세요.")
        return report

    def evaluate(self, request_id):
        """Synchronous helper for module tests/export; HTTP uses submit_evaluation."""
        row, context = self._prepare_evaluation(request_id)
        return self._finish_evaluation(context, calculate(context))

    def submit_evaluation(self, request_id):
        return self.evaluations.submit(request_id)

    def cancel_evaluation(self, request_id):
        return self.evaluations.cancel(request_id)

    def _approval_context_valid(self, row, report, current):
        body = NewRequest.model_validate(row["request"])
        if isinstance(body.command, TEPCommand) or report.get("tep_simulation") is not None:
            return False
        try:
            review = EvidenceReview.model_validate(report["evidence"])
            result = SimulationResult.model_validate(report["simulation"])
            results_valid = (result.status == "completed" and evidence_issue(review) is None
                and simulation_issue(result) is None
                and not physical_risk(result) and coverage_issue(result) is None
                and {s.kind for s in result.scenarios} == {"normal", "degraded_cooling"}
                and all(s.baseline_peak_c <= LIMIT_C and s.candidate_peak_c <= LIMIT_C for s in result.scenarios))
        except (ValueError, TypeError, KeyError, OSError):
            return False
        return (type(self.adapter) is DemoAdapter
            and results_valid
            and (report.get("assessment") or {}).get("threshold_c") == review_policy.settings()[1]
            and report.get("execution_scope") == "virtual"
            and report.get("can_approve") is True and report["verdict"] == "awaiting_approval"
            and report["revision"] == row["revision"]
            and report["policy_version"] == POLICY_VERSION
            and report["model_version"] == simulator.MODEL_VERSION
            and digest({k: v for k, v in report.items() if k != "digest"}) == report["digest"]
            and digest(body.command.model_dump()) == report["command_digest"]
            and state_digest(current) == report["snapshot_digest"]
            and 0 <= time.time() - report["snapshot"]["observed_at"] <= SNAPSHOT_TTL_S
            and 0 <= time.time() - current.observed_at <= SNAPSHOT_TTL_S
            and scope_issue(body, current, report["model_version"], report["execution_scope"]) is None)

    def decide(self, request_id, body, actor):
        if actor not in {"operator", "approver"} or (body.decision != "request_retest" and actor != "approver"):
            raise HTTPException(403, "승인 담당자만 판단할 수 있습니다.")
        with self.lock:
            row = self.get(request_id)
            report = row["report"]
            if body.decision == "request_retest":
                if not report or body.report_digest != report["digest"] or row["status"] in {"evaluating", "executing", "completed", "execution_unknown"}:
                    raise HTTPException(409, "현재 보고서의 재시험을 요청할 수 없습니다.")
                row.update(status="hold", approval=None)
                self.event(row, "request_retest", actor=actor, reason=body.reason)
                self.store.save(row)
                return row
            if not report or row["status"] != "awaiting_approval" or body.report_digest != report["digest"]:
                raise HTTPException(409, "승인 가능한 최신 보고서가 아닙니다.")
            if body.decision == "reject":
                row["status"] = "rejected"
            else:
                if not self._approval_context_valid(row, report, self.adapter.read_state()):
                    row.update(status="revalidation_required", approval=None)
                    self.event(row, "execution_denied", reason="승인 대상 상태·보고서·정책이 달라졌습니다.")
                    self.store.save(row)
                    raise HTTPException(409, "승인 전에 재검증이 필요합니다.")
                row["approval"] = {"actor": actor, "report_digest": report["digest"],
                    "expires_at": time.time() + APPROVAL_TTL_S, "reason": body.reason}
                row["status"] = "approved"
            self.event(row, body.decision, actor=actor, reason=body.reason)
            self.store.save(row)
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
            valid = (self._approval_context_valid(row, report, current)
                and approval["expires_at"] > time.time()
                and approval["report_digest"] == report["digest"])
            if not valid:
                row["status"] = "revalidation_required"
                row["approval"] = None
                self.event(row, "execution_denied", reason="승인 만료 또는 검증 대상 변경")
                self.store.save(row)
                raise HTTPException(409, "승인 만료 또는 검증 대상 변경: 재검증이 필요합니다.")
            execution_id = str(uuid.uuid4())
            row["status"] = "executing"
            row["execution"] = {"execution_id": execution_id, "status": "unknown"}
            self.event(row, "execution_reserved", execution_id=execution_id)
            self.store.save(row)  # Commit intent before applying even the virtual command.
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
            self.store.save(row)
            return row


    def send_notification(self, request_id, notification_id):
        with self.lock:
            row = self.get(request_id)
            note = next((n for n in self.store.notifications(request_id) if n["id"] == notification_id), None)
            if note is None:
                raise HTTPException(404, "알림을 찾을 수 없습니다.")
            if note["status"] == "sent":
                return note
            if note["status"] != "queued" or row["status"] != "awaiting_approval" or row["report"]["digest"] != note["report_digest"]:
                raise HTTPException(409, "현재 보고서의 대기 중 알림만 발송할 수 있습니다.")
            if not self._approval_context_valid(row, row["report"], self.adapter.read_state()):
                raise HTTPException(409, "오래되었거나 변경된 보고서입니다. 재검증 후 알림을 발송하세요.")
            cfg = notifications.config()
            if not cfg["configured"] or cfg["recipient"] != note["recipient"]:
                raise HTTPException(409, "SMTP 설정을 확인하고 재검증하세요.")
            note.update(status="sending", attempts=note["attempts"] + 1, detail="발송 중")
            self.event(row, "notification_sending")
            self.store.save(row, notification=note)
            try:
                notifications.send(note, row, self.store.contact(request_id))
                note.update(status="sent", sent_at=time.time(), detail="SMTP 서버가 알림을 접수했습니다. 수신·확인·승인 완료를 뜻하지 않습니다.")
                self.event(row, "notification_sent")
            except Exception:
                note.update(status="unknown", detail="발송 결과를 확인하지 못했습니다. 수신 여부를 확인하세요. 자동 재발송하지 않습니다.")
                self.event(row, "notification_unknown", reason=note["detail"])
            self.store.save(row, notification=note)
            return note
