from datetime import datetime

import pytest

from app.bazi_engine import BirthInput, CalculationOptions
from app.bazi_engine.calendar import adjust_birth_time, standard_meridian_for_birth


def test_shanghai_standard_meridian_is_120_degrees():
    birth = BirthInput(local_datetime="1993-03-09 07:00:00")

    assert standard_meridian_for_birth(birth) == 120


def test_longitude_correction_matches_existing_four_minutes_per_degree_rule():
    birth = BirthInput(
        local_datetime="1993-03-09 07:00:00",
        longitude=111.75,
    )

    result = adjust_birth_time(birth, CalculationOptions())

    assert result.longitude_correction_minutes == -33
    assert result.adjusted_datetime == datetime(1993, 3, 9, 6, 27)
    assert result.standard_meridian == 120
    assert result.warnings == []


def test_true_solar_time_can_be_disabled():
    birth = BirthInput(
        local_datetime="1993-03-09 07:00:00",
        longitude=111.75,
    )

    result = adjust_birth_time(
        birth,
        CalculationOptions(use_true_solar_time=False),
    )

    assert result.adjusted_datetime == birth.local_datetime
    assert result.longitude_correction_minutes == 0
    assert result.standard_meridian is None


def test_missing_longitude_is_explicitly_reported():
    birth = BirthInput(
        local_datetime="1993-03-09 07:00:00",
        birthplace="广东阳春",
    )

    result = adjust_birth_time(birth, CalculationOptions())

    assert result.adjusted_datetime == birth.local_datetime
    assert [warning.code for warning in result.warnings] == [
        "true_solar_time_not_applied"
    ]


def test_equation_of_time_is_not_silently_approximated():
    birth = BirthInput(
        local_datetime="1993-03-09 07:00:00",
        longitude=111.75,
    )

    with pytest.raises(NotImplementedError, match="verified ephemeris"):
        adjust_birth_time(
            birth,
            CalculationOptions(equation_of_time=True),
        )
