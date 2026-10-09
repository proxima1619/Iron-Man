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

class TEPCommand(StrictModel):
    type: Literal["set_tep_cooling_water"]
    variable: Literal["XMV10", "XMV11"]
    value: float
    duration_s: int = Field(default=600, ge=1, le=3600, strict=True)
    sample_period_s: int = Field(default=10, ge=1, le=60, strict=True)

class NewRequest(StrictModel):
    equipment_id: Literal["cooling-demo-01", "tep-sim-01"] = "cooling-demo-01"
    purpose: str = Field(default="냉각 펌프 속도 변경 검토", min_length=1, max_length=500)
    command: Command | TEPCommand
    requester_contact: str | None = Field(default=None, exclude=True, max_length=254,
        pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")

    @model_validator(mode="after")
    def command_equipment(self):
        if (self.equipment_id == "tep-sim-01") != isinstance(self.command, TEPCommand):
            raise ValueError("TEP commands require tep-sim-01; pump commands require cooling-demo-01")
        return self

class TEPState(StrictModel):
    profile: Literal["nist-teinit-base-case-v1"] = "nist-teinit-base-case-v1"
    data_origin: Literal["simulation"] = "simulation"
    configured_at: float
    model_version: str
    # This identifies initialization code, not a snapshot reconstructed from sensors.
    source_sha256: str
    wrapper_sha256: str
    variables_sha256: str

class TEPVariable(StrictModel):
    name: str
    unit: Literal["percent_full_scale", "kscm/h", "kg/h", "kPa_gauge", "percent", "degC", "m3/h", "kW", "mole_percent"]

class TEPShutdownRule(StrictModel):
    quantity: str
    unit: str
    minimum: float | None = None
    maximum: float | None = None
    source: Literal["nist_tefunc_internal_shutdown"] = "nist_tefunc_internal_shutdown"

class TEPPoint(StrictModel):
    time_s: float = Field(ge=0)
    xmv: list[float] = Field(min_length=12, max_length=12)
    xmeas: list[float] = Field(min_length=41, max_length=41)
    actual_cooling_setting: list[float] = Field(min_length=2, max_length=2)

class TEPBranch(StrictModel):
    points: list[TEPPoint] = Field(min_length=2)
    csv_sha256: str

class TEPMetric(StrictModel):
    baseline_min: float
    baseline_max: float
    candidate_min: float
    candidate_max: float
    final_delta: float
    max_abs_delta: float = Field(ge=0)

class TEPConfiguration(StrictModel):
    variable: Literal["XMV10", "XMV11"]
    candidate_value: float
    horizon_s: int = Field(ge=1, le=3600, strict=True)
    sample_period_s: int = Field(ge=1, le=60, strict=True)
    integration_step_s: Literal[0.1] = 0.1
    integrator: Literal["forward_euler"] = "forward_euler"
    controller: Literal["none_open_loop_hold"] = "none_open_loop_hold"
    operating_mode: Literal["original_teinit_base_case"] = "original_teinit_base_case"
    random_seed: Literal[1431655765] = 1431655765
    disturbances: list[int] = Field(default_factory=lambda: [0] * 20, min_length=20, max_length=20)

class TEPProvenance(StrictModel):
    source_url: str
    source_commit: str
    source_files_sha256: dict[str, str]
    wrapper_sha256: str
    binary_sha256: str
    compiler: str
    compiler_flags: list[str]
    platform: str
    initial_state: list[float] = Field(min_length=50, max_length=50)
    initial_xmv: list[float] = Field(min_length=12, max_length=12)
    initial_state_sha256: str
    license: str

class TEPResult(StrictModel):
    schema_version: Literal["tep-1.0"] = "tep-1.0"
    data_origin: Literal["simulation"] = "simulation"
    mock: Literal[False] = False
    status: Literal["completed", "out_of_domain", "failed"]
    model_version: str
    configuration: TEPConfiguration
    variables: dict[str, TEPVariable]
    core_shutdown_rules: list[TEPShutdownRule]
    provenance: TEPProvenance | None = None
    baseline: TEPBranch | None = None
    candidate: TEPBranch | None = None
    comparison: dict[str, TEPMetric] = Field(default_factory=dict)
    failure_code: str | None = None
    detail: str
    field_validation: Literal["not_performed_no_measured_data"] = "not_performed_no_measured_data"

    @model_validator(mode="after")
    def complete_pair(self):
        if self.status != "completed":
            if self.baseline or self.candidate or self.comparison or not self.failure_code:
                raise ValueError("failed TEP run must not publish success metrics")
            return self
        if not self.provenance or not self.baseline or not self.candidate or self.failure_code:
            raise ValueError("completed TEP run requires both branches and provenance")
        c = self.configuration
        if (not 0 <= c.candidate_value <= 100 or not 1 <= c.horizon_s <= 1800
            or c.horizon_s % c.sample_period_s or any(c.disturbances)):
            raise ValueError("unsupported TEP execution configuration")
        expected = list(range(0, c.horizon_s + 1, c.sample_period_s))
        if any([p.time_s for p in b.points] != expected for b in (self.baseline, self.candidate)):
            raise ValueError("missing, unordered or mismatched TEP time axis")
        if self.baseline.points[0] != self.candidate.points[0]:
            raise ValueError("TEP branches require the same initial state and observation")
        keys = {f"XMEAS{i}" for i in range(1, 42)}
        variable_keys = keys | {f"XMV{i}" for i in range(1,13)} | {"ACTUAL_XMV10", "ACTUAL_XMV11"}
        if set(self.comparison) != keys or set(self.variables) != variable_keys:
            raise ValueError("TEP measurements require definitions and comparison metrics")
        initial = self.provenance.initial_xmv
        index = int(c.variable[3:]) - 1
        candidate = list(initial)
        candidate[index] = c.candidate_value
        if (any(p.xmv != initial for p in self.baseline.points)
            or self.candidate.points[0].xmv != initial
            or any(p.xmv != candidate for p in self.candidate.points[1:])):
            raise ValueError("TEP branch inputs differ from captured execution configuration")
        for i in range(41):
            a = [p.xmeas[i] for p in self.baseline.points]
            b = [p.xmeas[i] for p in self.candidate.points]
            expected_metric = TEPMetric(baseline_min=min(a), baseline_max=max(a), candidate_min=min(b),
                candidate_max=max(b), final_delta=b[-1]-a[-1], max_abs_delta=max(abs(y-x) for x,y in zip(a,b)))
            if self.comparison[f"XMEAS{i+1}"] != expected_metric:
                raise ValueError("TEP comparison differs from the reported time series")
        return self

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
    snapshot: Snapshot | TEPState
    snapshot_digest: str
    model_version: str
    policy_version: str
    execution_scope: Literal["virtual", "unconfigured"] = "unconfigured"
    mock: bool
    can_approve: bool
    evidence: EvidenceReview | None
    simulation: SimulationResult | None
    tep_simulation: TEPResult | None = None
    verdict: Literal["blocked", "hold", "awaiting_approval"]
    reason_code: Literal[
        "INVALID_STATE", "POLICY_VIOLATION", "LIMIT_EXCEEDED", "DEMO_PASS",
        "EVIDENCE_INCOMPLETE", "SIMULATION_INCOMPLETE", "MODULE_FAILURE",
        "MATERIAL_DEVIATION", "LIVE_POLICY_NOT_CONFIGURED", "DEMO_POLICY_OUT_OF_SCOPE", "EVALUATION_CONTEXT_CHANGED",
        "EVALUATION_TIMEOUT", "EVALUATION_CANCELLED", "WORKER_FAILURE",
        "TEP_POLICY_NOT_CONFIGURED",
    ]
    reason: str
    digest: str
    assessment: "ReviewAssessment | None" = None

    @model_validator(mode="after")
    def tep_hold_only(self):
        if isinstance(self.snapshot, TEPState) or self.tep_simulation is not None:
            if (self.can_approve or self.verdict != "hold" or self.execution_scope != "unconfigured"
                or self.simulation is not None or self.assessment is not None or self.evidence is not None):
                raise ValueError("TEP results have no approval/execution/evidence policy configured")
        return self

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


class RecordFeedback(StrictModel):
    request_id: str
    record_revision: int
    record_digest: str
    report_digest: str | None
    generated_at: float
    model: str
    status: Literal["completed", "insufficient"]
    advisory_only: Literal[True] = True
    summary: str
    result_interpretation: str
    model_limitations: list[str]
    missing_conditions: list[str]
    recommended_checks: list[str]
    evidence: EvidenceReview


class EvidenceSourceSummary(StrictModel):
    source_id: str
    title: str
    source_type: str
    source_url: str | None
    publisher: str
    locator: str


class EvidenceCatalog(StrictModel):
    mode: Literal["fixture", "live", "invalid"]
    source_mode: Literal["local", "europepmc", "invalid"]
    api_key_configured: bool
    model_configured: bool
    ready: bool
    sources: list[EvidenceSourceSummary]
    issues: list[str]
    catalog_error: bool


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
