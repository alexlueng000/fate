from datetime import datetime

import pytest
from pydantic import ValidationError

from app.bazi_engine import (
    BirthInput,
    CalculationOptions,
    CalculationVersion,
    Pillar,
    chart_from_legacy_paipan,
)


LEGACY_PAIPAN = {
    "mingpan": {
        "gender": "女",
        "four_pillars": {
            "year": ["癸", "酉"],
            "month": ["乙", "卯"],
            "day": ["己", "丑"],
            "hour": ["丁", "卯"],
        },
        "dayun": [
            {"age": 8, "start_year": 2025, "pillar": ["辛", "亥"]},
        ],
        "solar_date": "1993-03-09 06:42:00",
    }
}


def test_pillar_accepts_valid_ganzhi_and_serializes_stably():
    pillar = Pillar(stem="甲", branch="子")

    assert pillar.ganzhi() == "甲子"
    assert pillar.model_dump(mode="json") == {"stem": "甲", "branch": "子"}


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"stem": "木", "branch": "子"}, "invalid heavenly stem"),
        ({"stem": "甲", "branch": "甲"}, "invalid earthly branch"),
    ],
)
def test_pillar_rejects_invalid_characters(value, message):
    with pytest.raises(ValidationError, match=message):
        Pillar.model_validate(value)


def test_birth_input_validates_timezone_coordinates_and_leap_month():
    birth = BirthInput(
        calendar="lunar",
        local_datetime="1993-02-16 07:00:00",
        timezone="Asia/Shanghai",
        birthplace=" 广东阳春 ",
        latitude=22.17,
        longitude=111.78,
        leap_month=True,
    )

    assert birth.birthplace == "广东阳春"
    assert birth.local_datetime == datetime(1993, 2, 16, 7, 0)

    with pytest.raises(ValidationError, match="leap_month"):
        BirthInput(
            calendar="gregorian",
            local_datetime="1993-03-09 07:00:00",
            leap_month=True,
        )

    with pytest.raises(ValidationError, match="unknown IANA timezone"):
        BirthInput(
            local_datetime="1993-03-09 07:00:00",
            timezone="Mars/Olympus",
        )


def test_legacy_paipan_adapter_preserves_chart_and_version():
    birth = BirthInput(
        calendar="gregorian",
        local_datetime="1993-03-09 07:00:00",
        birthplace="广东阳春",
        longitude=111.78,
    )
    options = CalculationOptions(
        use_true_solar_time=True,
        equation_of_time=False,
        day_boundary_rule="00:00",
    )

    chart = chart_from_legacy_paipan(LEGACY_PAIPAN, birth=birth, options=options)

    assert chart.gender == "女"
    assert chart.adjusted_datetime == datetime(1993, 3, 9, 6, 42)
    assert chart.four_pillars.year.ganzhi() == "癸酉"
    assert chart.four_pillars.day.ganzhi() == "己丑"
    assert chart.dayun[0].start_age == 8
    assert chart.dayun[0].pillar.ganzhi() == "辛亥"
    assert chart.metadata.version == CalculationVersion.LEGACY_V1
    assert chart.metadata.source == "legacy_adapter"
    assert chart.warnings == []

    restored = type(chart).model_validate_json(chart.model_dump_json())
    assert restored == chart


def test_legacy_adapter_marks_inferred_birth_context():
    chart = chart_from_legacy_paipan(LEGACY_PAIPAN)

    assert chart.birth.local_datetime == chart.adjusted_datetime
    assert chart.birth.birthplace is None
    assert [warning.code for warning in chart.warnings] == [
        "legacy_birth_context_incomplete"
    ]


def test_legacy_adapter_skips_empty_pre_dayun_entry_with_warning():
    payload = {
        **LEGACY_PAIPAN["mingpan"],
        "dayun": [
            {"age": 0, "start_year": 1993, "pillar": []},
            {"age": 8, "start_year": 2001, "pillar": ["辛", "亥"]},
        ],
    }

    chart = chart_from_legacy_paipan(payload)

    assert [period.pillar.ganzhi() for period in chart.dayun] == ["辛亥"]
    assert "legacy_empty_dayun_skipped" in {
        warning.code for warning in chart.warnings
    }


def test_legacy_adapter_rejects_incomplete_chart():
    invalid = {
        "gender": "男",
        "solar_date": "1993-03-09 07:00:00",
        "four_pillars": {"year": ["甲", "子"]},
    }

    with pytest.raises(ValueError):
        chart_from_legacy_paipan(invalid)
