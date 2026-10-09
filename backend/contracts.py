"""Shared contract: owner 1; coordinate changes with all module owners."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

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

class SimulationResult(StrictModel):
    mock: Literal[True] = True
    model_version: str
    scenarios: list[dict]
    limitation: str

class EvidenceReview(StrictModel):
    mock: Literal[True] = True
    status: Literal["demo_fixture"] = "demo_fixture"
    cards: list[dict]
    proposed_tests: list[Scenario]
    limitation: str

class DecisionInput(StrictModel):
    report_digest: str
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=500)

class ExecutionInput(StrictModel):
    report_digest: str

class DemoStateInput(StrictModel):
    load_ratio: float = Field(ge=0, le=2, allow_inf_nan=False)
    sensor_quality: Literal["valid", "invalid"] = "valid"
