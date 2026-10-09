"""Private LLM output schema; public Scenario remains owned by gateway."""
from typing import Literal
from pydantic import Field
from backend.contracts import StrictModel


class Claim(StrictModel):
    source_id: str
    claim: str = Field(min_length=1, max_length=1500)
    stance: Literal["support", "counter", "limitation"]
    excerpt: str = Field(min_length=1, max_length=500)
    applicability: Literal["applicable", "partial", "mismatch", "unknown"]
    matched_conditions: list[str] = Field(max_length=10)
    missing_conditions: list[str] = Field(max_length=10)
    proposed_test: Literal["degraded_cooling"] | None


class Analysis(StrictModel):
    cards: list[Claim] = Field(max_length=12)
    missing_conditions: list[str] = Field(max_length=10)
