"""Versioned Four Pillars and Da Yun chart construction."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import metadata
from typing import Any, Optional

from .calendar import adjust_birth_time
from .schemas import (
    BaziChart,
    BirthInput,
    CalculationMetadata,
    CalculationOptions,
    CalculationWarning,
    DaYunPeriod,
    FourPillars,
    Pillar,
)
from .versions import CURRENT_CALCULATION_VERSION


def _load_lunar_python():
    try:
        from lunar_python import Lunar, Solar
        from lunar_python.eightchar import Yun
    except ImportError as exc:
        raise RuntimeError(
            "lunar-python is required to build a Bazi chart"
        ) from exc
    return Lunar, Solar, Yun


def _provider_version() -> str:
    try:
        return f"lunar-python/{metadata.version('lunar-python')}"
    except metadata.PackageNotFoundError:
        return "lunar-python/unknown"


def _pillar(value: str, field: str) -> Pillar:
    normalized = str(value or "").strip().replace(" ", "")
    if len(normalized) != 2:
        raise ValueError(f"calendar provider returned invalid {field}: {value!r}")
    return Pillar(stem=normalized[0], branch=normalized[1])


def _solar_datetime(solar: Any) -> datetime:
    return datetime(
        solar.getYear(),
        solar.getMonth(),
        solar.getDay(),
        solar.getHour(),
        solar.getMinute(),
        solar.getSecond(),
    )


def build_chart(
    birth: BirthInput,
    gender: str,
    *,
    options: Optional[CalculationOptions] = None,
    calculated_at: Optional[datetime] = None,
) -> BaziChart:
    """Build a canonical chart without HTTP, database, or geocoding access."""

    if gender not in ("男", "女"):
        raise ValueError("gender must be 男 or 女")

    calculation_options = options or CalculationOptions()
    if calculation_options.day_boundary_rule != "00:00":
        raise NotImplementedError(
            "day_boundary_rule=23:00 is not enabled until boundary goldens exist"
        )

    adjustment = adjust_birth_time(birth, calculation_options)
    adjusted_input = adjustment.adjusted_datetime
    if not isinstance(adjusted_input, datetime):
        raise TypeError("adjusted birth time must be a datetime")

    Lunar, Solar, Yun = _load_lunar_python()
    if birth.calendar == "lunar":
        lunar_month = -adjusted_input.month if birth.leap_month else adjusted_input.month
        lunar = Lunar.fromYmdHms(
            adjusted_input.year,
            lunar_month,
            adjusted_input.day,
            adjusted_input.hour,
            adjusted_input.minute,
            adjusted_input.second,
        )
        solar = lunar.getSolar()
    else:
        solar = Solar.fromYmdHms(
            adjusted_input.year,
            adjusted_input.month,
            adjusted_input.day,
            adjusted_input.hour,
            adjusted_input.minute,
            adjusted_input.second,
        )
        lunar = solar.getLunar()

    eight_char = lunar.getEightChar()
    four_pillars = FourPillars(
        year=_pillar(eight_char.getYear(), "year pillar"),
        month=_pillar(eight_char.getMonth(), "month pillar"),
        day=_pillar(eight_char.getDay(), "day pillar"),
        hour=_pillar(eight_char.getTime(), "hour pillar"),
    )

    gender_code = 1 if gender == "男" else 0
    dayun: list[DaYunPeriod] = []
    warnings = list(adjustment.warnings)
    for item in Yun(eight_char, gender_code).getDaYun():
        ganzhi = str(item.getGanZhi() or "").strip().replace(" ", "")
        if not ganzhi:
            warnings.append(
                CalculationWarning(
                    code="empty_dayun_period_skipped",
                    field="dayun",
                    severity="info",
                    message="Calendar provider returned a pre-Da-Yun period without a pillar.",
                )
            )
            continue
        dayun.append(
            DaYunPeriod(
                start_age=item.getStartAge(),
                start_year=item.getStartYear(),
                pillar=_pillar(ganzhi, "Da Yun pillar"),
            )
        )

    run_time = calculated_at or datetime.now(timezone.utc)
    if run_time.tzinfo is None or run_time.utcoffset() is None:
        run_time = run_time.replace(tzinfo=timezone.utc)
    else:
        run_time = run_time.astimezone(timezone.utc)

    return BaziChart(
        gender=gender,
        birth=birth,
        options=calculation_options,
        adjusted_datetime=_solar_datetime(solar),
        four_pillars=four_pillars,
        dayun=dayun,
        warnings=warnings,
        metadata=CalculationMetadata(
            version=CURRENT_CALCULATION_VERSION,
            provider=_provider_version(),
            calculated_at=run_time,
            source="engine",
        ),
    )
