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
    requester_contact: str | None = Field(default=None, exclude=True, max_length=254,
        pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")

class Snapshot(StrictModel):
    revision: int
    temperature_c: float
    load_ratio: float
    pump_speed_pct: float
    observed_at: float
    sensor_quality: Literal["valid", "invalid"] = "valid"
    data_origin: Literal["synthetic"] = "synthetic"
    # Nullable additions let historical v1/v2 reports retain their original meaning.
    target_pump_speed_pct: float | None = None
    simulation_time_s: float = Field(default=0, ge=0)
    model_version: str | None = Field(default=None, min_length=1)
    calculated_at: float | None = None
    domain_status: Literal["ready", "out_of_domain"] = "ready"
    domain_reason: str | None = None

class Scenario(StrictModel):
    kind: Literal["normal", "degraded_cooling"]
    evidence_id: str | None = None

class ParameterRange(StrictModel):
    minimum: float
    maximum: float

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum <= 0 or self.maximum < self.minimum:
            raise ValueError("parameter range must be positive and ordered")
        return self

class BranchAssessment(StrictModel):
    peak_c: float
    first_exceeded_s: float | None = Field(default=None, ge=0)
    equilibrium_c: float | None = None
    equilibrium_status: Literal["finite", "unbounded_heating", "no_unique_equilibrium"]
    thermal_time_constant_s: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def equilibrium_fields(self):
        if (self.equilibrium_status == "finite") != (self.equilibrium_c is not None and self.thermal_time_constant_s is not None):
            raise ValueError("finite equilibrium requires temperature and thermal time constant")
        if self.equilibrium_status != "finite" and (self.equilibrium_c is not None or self.thermal_time_constant_s is not None):
            raise ValueError("nonfinite equilibrium must not publish finite metrics")
        return self

class SensitivityAssessment(StrictModel):
    status: Literal["completed", "out_of_domain"]
    baseline_worst_peak_c: float | None = None
    candidate_worst_peak_c: float | None = None
    baseline_worst_equilibrium_c: float | None = None
    candidate_worst_equilibrium_c: float | None = None
    evaluated_parameter_sets: int = Field(ge=0, strict=True)
    limitation: str

    @model_validator(mode="after")
    def coverage(self):
        metrics = (self.baseline_worst_peak_c, self.candidate_worst_peak_c,
                   self.baseline_worst_equilibrium_c, self.candidate_worst_equilibrium_c)
        if self.status == "completed" and (self.evaluated_parameter_sets != 16 or any(v is None for v in metrics)):
            raise ValueError("completed sensitivity requires all 16 parameter sets and metrics")
        if self.status != "completed" and any(v is not None for v in metrics):
            raise ValueError("unsupported sensitivity must not publish partial metrics")
        return self

class PhysicalAssessment(StrictModel):
    version: Literal["cooling-assessment-v4"] = "cooling-assessment-v4"
    horizon_s: int = Field(ge=3600, le=3600, strict=True)
    baseline: BranchAssessment
    candidate: BranchAssessment
    parameter_origin: Literal["demo_assumption"] = "demo_assumption"
    calibration_status: Literal["not_calibrated"] = "not_calibrated"
    parameter_ranges: dict[str, ParameterRange]
    sensitivity: SensitivityAssessment

    @model_validator(mode="after")
    def bounded_crossing_time(self):
        if any(branch.first_exceeded_s is not None and branch.first_exceeded_s > self.horizon_s
               for branch in (self.baseline, self.candidate)):
            raise ValueError("first crossing must be within the assessed horizon")
        return self

class ScenarioResult(StrictModel):
    kind: Literal["normal", "degraded_cooling"]
    evidence_id: str | None = None
    baseline_peak_c: float
    candidate_peak_c: float
    limit_c: float
    exceeded: bool = Field(strict=True)
    value_origin: Literal["hardcoded_demo_fixture", "model_calculation"]
    # Missing on historical reports; never implies the new assessment passed.
    physical_assessment: PhysicalAssessment | None = None

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
    source_type: Literal["team_authored_fixture", "team_authored_demo", "paper", "manual", "field_record"]
    excerpt: str | None = None
    publisher: str | None = None
    version: str | None = None
    published_at: str | None = None
    usage: str | None = None
    proposed_test: Literal["degraded_cooling"] | None = None
    parameter_origin: Literal["demo_assumption"] | None = None
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
    execution_scope: Literal["virtual", "unconfigured"] = "unconfigured"
    mock: bool
    can_approve: bool
    evidence: EvidenceReview | None
    simulation: SimulationResult | None
    verdict: Literal["blocked", "hold", "awaiting_approval"]
    reason_code: Literal[
        "INVALID_STATE", "POLICY_VIOLATION", "LIMIT_EXCEEDED", "DEMO_PASS",
        "EVIDENCE_INCOMPLETE", "SIMULATION_INCOMPLETE", "MODULE_FAILURE",
        "MATERIAL_DEVIATION", "LIVE_POLICY_NOT_CONFIGURED", "DEMO_POLICY_OUT_OF_SCOPE", "EVALUATION_CONTEXT_CHANGED",
        "EVALUATION_TIMEOUT", "EVALUATION_CANCELLED", "WORKER_FAILURE",
    ]
    reason: str
    digest: str
    assessment: "ReviewAssessment | None" = None

class Approval(StrictModel):
    actor: str
    report_digest: str
    expires_at: float
    reason: str

class AuditEvent(StrictModel):
    kind: Literal["created", "evaluation_failed", "evaluated", "approve", "reject",
                  "execution_denied", "execution_reserved", "executed", "execution_unknown",
                  "evaluation_interrupted", "execution_interrupted", "evaluation_started", "request_retest",
                  "notification_queued", "notification_sending", "notification_sent", "notification_unknown"]
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
    decision: Literal["approve", "reject", "request_retest"]
    reason: str = Field(min_length=1, max_length=500)

class ExecutionInput(StrictModel):
    report_digest: str

class DemoStateInput(StrictModel):
    load_ratio: float = Field(ge=0, le=2, allow_inf_nan=False)
    sensor_quality: Literal["valid", "invalid"] = "valid"


class DemoAdvanceInput(StrictModel):
    seconds_s: int = Field(ge=1, le=3600, strict=True)


class RequestHistory(StrictModel):
    reports: list[DecisionReport]
    approvals: list[Approval]


class DeviationMetric(StrictModel):
    kind: Literal["normal", "degraded_cooling"]
    baseline_peak_c: float
    candidate_peak_c: float
    absolute_delta_c: float
    material: bool | None


class ReviewAssessment(StrictModel):
    comparison: Literal["baseline_candidate_peak"] = "baseline_candidate_peak"
    origin: Literal["synthetic_model"] = "synthetic_model"
    threshold_c: float | None
    status: Literal["threshold_not_configured", "within_tolerance", "material_deviation"]
    metrics: list[DeviationMetric]
    limitation: str


class ReviewContact(StrictModel):
    requester_contact: str | None
    verified: Literal[False] = False


class Notification(StrictModel):
    id: str
    request_id: str
    report_digest: str
    recipient: str | None
    status: Literal["not_configured", "queued", "sending", "sent", "unknown"]
    created_at: float
    sent_at: float | None = None
    attempts: int = 0
    detail: str


class SessionInfo(StrictModel):
    role: Literal["operator", "approver"]
    actor_label: str
    authentication: Literal["demo_token"] = "demo_token"
    storage: Literal["sqlite"] = "sqlite"
    synthetic_approval_enabled: bool
    negligible_delta_c: float | None
    notification_configured: bool
    virtual_only: Literal[True] = True


DecisionReport.model_rebuild()
RequestRecord.model_rebuild()
RequestHistory.model_rebuild()
