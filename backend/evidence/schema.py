"""Private LLM output schema; public Scenario remains owned by gateway."""
from typing import Literal
from pydantic import Field, field_validator
from backend.contracts import StrictModel


class ReviewText(StrictModel):
    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def meaningful_text(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("Review text must not be blank")
        if isinstance(value, list) and any(isinstance(item, str) and not item.strip() for item in value):
            raise ValueError("Review condition must not be blank")
        return value


class Claim(ReviewText):
    source_id: str
    claim: str = Field(min_length=1, max_length=1500)
    stance: Literal["support", "counter", "limitation"]
    excerpt: str = Field(min_length=1, max_length=500)
    applicability: Literal["applicable", "partial", "mismatch", "unknown"]
    matched_conditions: list[str] = Field(max_length=10)
    missing_conditions: list[str] = Field(max_length=10)
    # Unknown names are data to report as unverified, never executable scenarios.
    proposed_test: str | None = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class Analysis(ReviewText):
    cards: list[Claim] = Field(max_length=12)
    missing_conditions: list[str] = Field(max_length=10)


class RecordAnalysis(Analysis):
    summary: str = Field(min_length=1, max_length=1500)
    result_interpretation: str = Field(min_length=1, max_length=2500)
    model_limitations: list[str] = Field(min_length=1, max_length=10)
    recommended_checks: list[str] = Field(min_length=1, max_length=10)
