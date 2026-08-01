"""Pure time adjustments used before Four Pillars calculation."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import Field

from .schemas import (
    BirthInput,
    CalculationOptions,
    CalculationWarning,
    StrictModel,
)


class TimeAdjustment(StrictModel):
    adjusted_datetime: datetime
    longitude_correction_minutes: float = 0.0
    equation_of_time_minutes: float = 0.0
    standard_meridian: float | None = Field(default=None, ge=-180, le=180)
    warnings: list[CalculationWarning] = Field(default_factory=list)


def standard_meridian_for_birth(birth: BirthInput) -> float:
    """Return the timezone's non-DST standard meridian for the birth date."""

    timezone = ZoneInfo(birth.timezone)
    localized = birth.local_datetime.replace(tzinfo=timezone)
    utc_offset = localized.utcoffset()
    dst_offset = localized.dst()
    if utc_offset is None:
        raise ValueError(f"timezone has no UTC offset: {birth.timezone}")
    standard_offset = utc_offset - (dst_offset or timedelta(0))
    return standard_offset.total_seconds() / 3600 * 15


def adjust_birth_time(
    birth: BirthInput,
    options: CalculationOptions,
) -> TimeAdjustment:
    """Apply the configured longitude correction without external lookups.

    The existing production algorithm uses four minutes per longitude degree.
    This function generalizes its reference meridian using the configured IANA
    timezone while retaining exactly 120°E for Asia/Shanghai. Equation-of-time
    correction is intentionally rejected until an independently verified
    ephemeris implementation and boundary goldens are available.
    """

    if options.equation_of_time:
        raise NotImplementedError(
            "equation_of_time requires a verified ephemeris implementation"
        )

    if not options.use_true_solar_time:
        return TimeAdjustment(adjusted_datetime=birth.local_datetime)

    standard_meridian = standard_meridian_for_birth(birth)
    if birth.longitude is None:
        return TimeAdjustment(
            adjusted_datetime=birth.local_datetime,
            standard_meridian=standard_meridian,
            warnings=[
                CalculationWarning(
                    code="true_solar_time_not_applied",
                    field="birth.longitude",
                    message=(
                        "True solar time was requested but longitude was missing; "
                        "the original local time was retained."
                    ),
                )
            ],
        )

    correction_minutes = (birth.longitude - standard_meridian) * 4
    adjusted = birth.local_datetime + timedelta(minutes=correction_minutes)
    return TimeAdjustment(
        adjusted_datetime=adjusted,
        longitude_correction_minutes=correction_minutes,
        standard_meridian=standard_meridian,
    )
