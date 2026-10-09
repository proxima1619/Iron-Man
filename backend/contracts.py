"""Shared contract: owner 1; coordinate changes with all module owners."""
from typing import Literal
from pydantic import model_validator
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, revalidate_instances="always", json_schema_serialization_defaults_required=True)

class Command(StrictModel):
    type: Literal["set_pump_speed"] = "set_pump_speed"
    target_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    duration_s: int = Field(default=300, ge=1, le=3600, strict=True)

class NewRequest(StrictModel):
    equipment_id: Literal["cooling-demo-01"] = "cooling-demo-01"
    purpose: str = Field(default="냉각 펌프 속도 변경 검토", min_length=1, max_length=500)
    command: Command

class Snapshot(StrictModel):
    revision: int
    temperature_c: float
    load_ratio: float
    pump_speed_pct: float
    observed_at: float
    sensor_quality: Literal["valid", "invalid"] = "valid"
    data_origin: Literal["synthetic"] = "synthetic"

class Scenario(StrictModel):
    kind: Literal["normal", "degraded_cooling"]
    evidence_id: str | None = None

class ScenarioResult(StrictModel):
    kind: Literal["normal", "degraded_cooling"]
    evidence_id: str | None = None
    baseline_peak_c: float
    candidate_peak_c: float
    limit_c: float
    exceeded: bool = Field(strict=True)
    value_origin: Literal["hardcoded_demo_fixture", "model_calculation"]

    @model_validator(mode="after")
    def consistent_threshold(self):
        if self.exceeded != (self.candidate_peak_c > self.limit_c):
            raise ValueError("exceeded must match candidate_peak_c > limit_c")
        return self

class SimulationResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mock: bool = Field(strict=True)
    status: Literal["completed", "out_of_domain", "failed"]
    model_version: str = Field(min_length=1)
    scenarios: list[ScenarioResult] = Field(default_factory=list)
    limitation: str = Field(min_length=1)

    @model_validator(mode="after")
    def complete_results(self):
        if self.status == "completed" and not self.scenarios:
            raise ValueError("completed simulation requires scenario results")
        if self.status != "completed" and self.scenarios:
            raise ValueError("unavailable calculation must not include success metrics")
        kinds = [s.kind for s in self.scenarios]
        if len(kinds) != len(set(kinds)):
            raise ValueError("duplicate scenario result")
        if not self.mock and any(s.value_origin == "hardcoded_demo_fixture" for s in self.scenarios):
            raise ValueError("fixture values require mock=true")
        return self

class EvidenceCard(StrictModel):
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    stance: Literal["support", "counter", "limitation"]
    claim: str = Field(min_length=1)
    applicability: Literal["applicable", "partial", "mismatch", "unknown"]
    locator: str = Field(min_length=1)
    source_url: str | None = None
    source_type: Literal["team_authored_fixture", "paper", "manual", "field_record"]
    matched_conditions: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)

class EvidenceReview(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mock: bool = Field(strict=True)
    status: Literal["demo_fixture", "completed", "insufficient", "failed"]
    cards: list[EvidenceCard] = Field(default_factory=list)
    proposed_tests: list[Scenario] = Field(default_factory=list, max_length=3)
    limitation: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_evidence(self):
        ids = [card.evidence_id for card in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence ID")
        for test in self.proposed_tests:
            if test.evidence_id not in ids:
                raise ValueError("proposed test must reference an evidence card")
        if self.status == "demo_fixture" and not self.mock:
            raise ValueError("demo_fixture requires mock=true")
        if not self.mock and any(c.source_type == "team_authored_fixture" for c in self.cards):
            raise ValueError("fixture evidence requires mock=true")
        if self.status == "completed" and not self.cards:
            raise ValueError("completed review requires evidence")
        return self

RequestStatus = Literal[
    "draft", "evaluating", "blocked", "hold", "awaiting_approval", "approved",
    "rejected", "revalidation_required", "executing", "completed", "execution_unknown",
]

class DecisionReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    revision: int
    command_digest: str
    snapshot: Snapshot
    snapshot_digest: str
    model_version: str
    policy_version: str
    mock: bool
    can_approve: bool
    evidence: EvidenceReview | None
    simulation: SimulationResult | None
    verdict: Literal["blocked", "hold", "awaiting_approval"]
    reason_code: Literal[
        "INVALID_STATE", "POLICY_VIOLATION", "LIMIT_EXCEEDED", "DEMO_PASS",
        "EVIDENCE_INCOMPLETE", "SIMULATION_INCOMPLETE", "MODULE_FAILURE",
        "LIVE_POLICY_NOT_CONFIGURED", "EVALUATION_CONTEXT_CHANGED",
        "EVALUATION_TIMEOUT", "EVALUATION_CANCELLED", "WORKER_FAILURE",
    ]
    reason: str
    digest: str

class Approval(StrictModel):
    actor: str
    report_digest: str
    expires_at: float
    reason: str

class AuditEvent(StrictModel):
    kind: Literal["created", "evaluation_failed", "evaluated", "approve", "reject",
                  "execution_denied", "execution_reserved", "executed", "execution_unknown",
                  "evaluation_interrupted", "execution_interrupted", "evaluation_started"]
    at: float
    verdict: RequestStatus | None = None
    report_digest: str | None = None
    actor: str | None = None
    reason: str | None = None
    execution_id: str | None = None

class AppliedExecution(StrictModel):
    execution_id: str
    status: Literal["applied"]
    virtual: Literal[True]
    command: Command
    state: Snapshot

class UnknownExecution(StrictModel):
    execution_id: str
    status: Literal["unknown"]

class EvaluationTask(StrictModel):
    id: str
    revision: int
    status: Literal["running", "completed", "failed", "timed_out", "cancelled", "interrupted"]
    started_at: float
    deadline_at: float
    finished_at: float | None = None

class RequestRecord(StrictModel):
    id: str
    revision: int
    request: NewRequest
    status: RequestStatus
    report: DecisionReport | None
    approval: Approval | None
    execution: AppliedExecution | UnknownExecution | None
    events: list[AuditEvent]
    evaluation: EvaluationTask | None = None

class DecisionInput(StrictModel):
    report_digest: str
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=500)

class ExecutionInput(StrictModel):
    report_digest: str

class DemoStateInput(StrictModel):
    load_ratio: float = Field(ge=0, le=2, allow_inf_nan=False)
    sensor_quality: Literal["valid", "invalid"] = "valid"


class RequestHistory(StrictModel):
    reports: list[DecisionReport]
    approvals: list[Approval]
