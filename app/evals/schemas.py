"""Schemas for versioned Bazi golden datasets and evaluation reports."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import Field, field_validator, model_validator

from app.bazi_engine.schemas import (
    BirthInput,
    CalculationOptions,
    Pillar,
    StrictModel,
)


class GoldenStatus(str, Enum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    APPROVED = "approved"
    DISPUTED = "disputed"


class ExpectedFourPillars(StrictModel):
    year: str
    month: str
    day: str
    hour: str

    @field_validator("year", "month", "day", "hour")
    @classmethod
    def validate_pillar(cls, value: str) -> str:
        normalized = value.strip().replace(" ", "")
        Pillar.from_legacy(normalized)
        return normalized


class ExpectedDaYunPeriod(StrictModel):
    start_age: float = Field(ge=0)
    start_year: int = Field(ge=1, le=9999)
    pillar: str

    @field_validator("pillar")
    @classmethod
    def validate_pillar(cls, value: str) -> str:
        normalized = value.strip().replace(" ", "")
        Pillar.from_legacy(normalized)
        return normalized


class ExpectedChart(StrictModel):
    adjusted_datetime: Optional[datetime] = None
    four_pillars: Optional[ExpectedFourPillars] = None
    dayun: Optional[List[ExpectedDaYunPeriod]] = None

    @model_validator(mode="after")
    def require_at_least_one_expectation(self) -> "ExpectedChart":
        if (
            self.adjusted_datetime is None
            and self.four_pillars is None
            and self.dayun is None
        ):
            raise ValueError("expected chart must define at least one comparison field")
        return self


class GoldenProvenance(StrictModel):
    status: GoldenStatus = GoldenStatus.CANDIDATE
    sources: List[str] = Field(default_factory=list)
    reviewed_by: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def require_review_for_approved_case(self) -> "GoldenProvenance":
        if self.status == GoldenStatus.APPROVED and not self.reviewed_by:
            raise ValueError("approved cases require reviewed_by")
        return self


class ChartGoldenCase(StrictModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str = Field(min_length=1)
    gender: str
    input: BirthInput
    options: CalculationOptions = Field(default_factory=CalculationOptions)
    expected: ExpectedChart
    provenance: GoldenProvenance = Field(default_factory=GoldenProvenance)

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, value: str) -> str:
        if value not in ("男", "女"):
            raise ValueError("gender must be 男 or 女")
        return value

    @model_validator(mode="after")
    def require_full_expectations_for_release_goldens(self) -> "ChartGoldenCase":
        if self.provenance.status in (
            GoldenStatus.VERIFIED,
            GoldenStatus.APPROVED,
        ):
            if self.expected.four_pillars is None:
                raise ValueError("verified and approved cases require four_pillars")
        return self


class EvaluationDifference(StrictModel):
    field: str
    expected: Any
    actual: Any


class CaseEvaluationResult(StrictModel):
    case_id: str
    outcome: str
    differences: List[EvaluationDifference] = Field(default_factory=list)
    reason: Optional[str] = None

    @field_validator("outcome")
    @classmethod
    def validate_outcome(cls, value: str) -> str:
        if value not in ("passed", "failed", "skipped", "error"):
            raise ValueError(f"invalid evaluation outcome: {value}")
        return value


class ChartEvaluationReport(StrictModel):
    total: int
    eligible: int
    passed: int
    failed: int
    skipped: int
    errors: int
    pass_rate: float
    results: List[CaseEvaluationResult]

