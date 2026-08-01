"""Versioned data contracts shared by the Bazi Engine and Agent V2.

These models intentionally contain no HTTP, database, or LLM dependencies. They
describe calculation inputs and deterministic outputs so a chart can be stored,
replayed, compared, and evaluated across engine versions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .constants import EARTHLY_BRANCHES, HEAVENLY_STEMS
from .versions import CalculationVersion, CURRENT_CALCULATION_VERSION


Gender = Literal["男", "女"]
CalendarType = Literal["gregorian", "lunar"]
DayBoundaryRule = Literal["23:00", "00:00"]
WarningSeverity = Literal["info", "warning", "error"]

class StrictModel(BaseModel):
    """Base contract that rejects unrecognised fields."""

    model_config = ConfigDict(extra="forbid")


class BirthInput(StrictModel):
    """Birth data as entered by the user before calendar corrections."""

    calendar: CalendarType = "gregorian"
    local_datetime: datetime
    timezone: str = "Asia/Shanghai"
    birthplace: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    leap_month: bool = False

    @field_validator("local_datetime")
    @classmethod
    def require_naive_local_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is not None and value.utcoffset() is not None:
            raise ValueError("local_datetime must not include timezone information")
        return value

    @field_validator("timezone")
    @classmethod
    def require_valid_timezone(cls, value: str) -> str:
        timezone = value.strip()
        if not timezone:
            raise ValueError("timezone must not be empty")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {timezone}") from exc
        return timezone

    @field_validator("birthplace")
    @classmethod
    def normalize_birthplace(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_leap_month(self) -> "BirthInput":
        if self.leap_month and self.calendar != "lunar":
            raise ValueError("leap_month can only be used with the lunar calendar")
        return self


class CalculationOptions(StrictModel):
    """Rules that can materially change calculation results."""

    use_true_solar_time: bool = True
    equation_of_time: bool = False
    day_boundary_rule: DayBoundaryRule = "00:00"


class Pillar(StrictModel):
    stem: str = Field(min_length=1, max_length=1)
    branch: str = Field(min_length=1, max_length=1)

    @field_validator("stem")
    @classmethod
    def require_heavenly_stem(cls, value: str) -> str:
        if value not in HEAVENLY_STEMS:
            raise ValueError(f"invalid heavenly stem: {value}")
        return value

    @field_validator("branch")
    @classmethod
    def require_earthly_branch(cls, value: str) -> str:
        if value not in EARTHLY_BRANCHES:
            raise ValueError(f"invalid earthly branch: {value}")
        return value

    @classmethod
    def from_legacy(cls, value: Any) -> "Pillar":
        """Convert legacy ``[stem, branch]`` or a two-character string."""

        if isinstance(value, str):
            normalized = value.strip().replace(" ", "")
            if len(normalized) != 2:
                raise ValueError("legacy pillar string must contain two characters")
            return cls(stem=normalized[0], branch=normalized[1])
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return cls(stem=str(value[0]), branch=str(value[1]))
        if isinstance(value, Mapping):
            return cls.model_validate(value)
        raise ValueError("legacy pillar must be a two-item sequence, string, or mapping")

    def ganzhi(self) -> str:
        return f"{self.stem}{self.branch}"


class FourPillars(StrictModel):
    year: Pillar
    month: Pillar
    day: Pillar
    hour: Pillar


class DaYunPeriod(StrictModel):
    start_age: float = Field(ge=0)
    start_year: int = Field(ge=1, le=9999)
    pillar: Pillar


class CalculationWarning(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: WarningSeverity = "warning"
    field: Optional[str] = None


class CalculationMetadata(StrictModel):
    version: CalculationVersion = CURRENT_CALCULATION_VERSION
    provider: str = "fate-bazi-engine"
    calculated_at: Optional[datetime] = None
    source: Literal["engine", "legacy_adapter"] = "engine"


class BaziChart(StrictModel):
    """Canonical, versioned chart shared by Bazi Engine V2 consumers."""

    gender: Gender
    birth: BirthInput
    options: CalculationOptions = Field(default_factory=CalculationOptions)
    adjusted_datetime: datetime
    four_pillars: FourPillars
    dayun: List[DaYunPeriod] = Field(default_factory=list)
    warnings: List[CalculationWarning] = Field(default_factory=list)
    metadata: CalculationMetadata = Field(default_factory=CalculationMetadata)

    @field_validator("adjusted_datetime")
    @classmethod
    def require_naive_adjusted_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is not None and value.utcoffset() is not None:
            raise ValueError("adjusted_datetime must not include timezone information")
        return value


def chart_from_legacy_paipan(
    payload: Mapping[str, Any],
    *,
    birth: Optional[BirthInput] = None,
    options: Optional[CalculationOptions] = None,
) -> BaziChart:
    """Convert the existing ``calc_paipan``/chat payload into ``BaziChart``.

    Both the router response wrapper ``{"mingpan": ...}`` and the inner chat
    payload are supported. When the original birth input is unavailable, the
    legacy adjusted time is used as a best-effort local time and a warning is
    attached so callers cannot mistake inferred data for verified input.
    """

    raw: Mapping[str, Any] = payload.get("mingpan", payload)
    if not isinstance(raw, Mapping):
        raise ValueError("legacy paipan payload must be a mapping")

    solar_date = raw.get("solar_date")
    if not solar_date:
        raise ValueError("legacy paipan payload is missing solar_date")
    adjusted_datetime = datetime.fromisoformat(str(solar_date))

    warnings: List[CalculationWarning] = []
    if birth is None:
        birth = BirthInput(local_datetime=adjusted_datetime)
        warnings.append(
            CalculationWarning(
                code="legacy_birth_context_incomplete",
                field="birth",
                message=(
                    "Original birth input was unavailable; adjusted time was used "
                    "as local time and location fields remain unknown."
                ),
            )
        )

    legacy_four_pillars = raw.get("four_pillars")
    if not isinstance(legacy_four_pillars, Mapping):
        raise ValueError("legacy paipan payload is missing four_pillars")

    four_pillars = FourPillars(
        year=Pillar.from_legacy(legacy_four_pillars.get("year")),
        month=Pillar.from_legacy(legacy_four_pillars.get("month")),
        day=Pillar.from_legacy(legacy_four_pillars.get("day")),
        hour=Pillar.from_legacy(legacy_four_pillars.get("hour")),
    )

    dayun: List[DaYunPeriod] = []
    for item in raw.get("dayun") or []:
        if not isinstance(item, Mapping):
            raise ValueError("legacy dayun item must be a mapping")
        legacy_pillar = item.get("pillar", item.get("ganzhi"))
        if not legacy_pillar:
            warnings.append(
                CalculationWarning(
                    code="legacy_empty_dayun_skipped",
                    field="dayun",
                    severity="info",
                    message="Legacy pre-Da-Yun entry without a pillar was skipped.",
                )
            )
            continue
        dayun.append(
            DaYunPeriod(
                start_age=item.get("start_age", item.get("age")),
                start_year=item.get("start_year"),
                pillar=Pillar.from_legacy(legacy_pillar),
            )
        )

    return BaziChart(
        gender=raw.get("gender"),
        birth=birth,
        options=options or CalculationOptions(),
        adjusted_datetime=adjusted_datetime,
        four_pillars=four_pillars,
        dayun=dayun,
        warnings=warnings,
        metadata=CalculationMetadata(
            version=CalculationVersion.LEGACY_V1,
            source="legacy_adapter",
        ),
    )
