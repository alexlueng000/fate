from datetime import datetime, timezone

import pytest

from app.bazi_engine import BirthInput, CalculationOptions
from app.bazi_engine import chart as chart_module
from app.bazi_engine.chart import build_chart
from app.bazi_engine.versions import CalculationVersion


def test_build_chart_matches_known_lunar_python_chart():
    pytest.importorskip("lunar_python")
    birth = BirthInput(
        calendar="gregorian",
        local_datetime="1993-03-09 07:00:00",
        birthplace="广东阳春",
        longitude=120,
    )

    chart = build_chart(
        birth,
        "男",
        options=CalculationOptions(use_true_solar_time=True),
        calculated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    assert chart.adjusted_datetime == datetime(1993, 3, 9, 7, 0)
    assert chart.four_pillars.year.ganzhi() == "癸酉"
    assert chart.four_pillars.month.ganzhi() == "乙卯"
    assert chart.four_pillars.day.ganzhi() == "己丑"
    assert chart.metadata.version == CalculationVersion.ENGINE_V2
    assert chart.metadata.source == "engine"
    assert chart.metadata.calculated_at == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert all(period.pillar.ganzhi() for period in chart.dayun)


def test_build_chart_rejects_unverified_23_hour_boundary_rule():
    birth = BirthInput(local_datetime="1993-03-09 07:00:00", longitude=120)

    with pytest.raises(NotImplementedError, match="boundary goldens"):
        build_chart(
            birth,
            "女",
            options=CalculationOptions(day_boundary_rule="23:00"),
        )


def test_build_chart_provider_contract_and_empty_pre_dayun(monkeypatch):
    class FakeEightChar:
        def getYear(self):
            return "癸酉"

        def getMonth(self):
            return "乙卯"

        def getDay(self):
            return "己丑"

        def getTime(self):
            return "戊辰"

    class FakeSolarValue:
        def __init__(self, values):
            self.values = values

        def getLunar(self):
            return FakeLunarValue(self)

        def getYear(self):
            return self.values[0]

        def getMonth(self):
            return self.values[1]

        def getDay(self):
            return self.values[2]

        def getHour(self):
            return self.values[3]

        def getMinute(self):
            return self.values[4]

        def getSecond(self):
            return self.values[5]

    class FakeSolar:
        @staticmethod
        def fromYmdHms(*values):
            return FakeSolarValue(values)

    class FakeLunarValue:
        def __init__(self, solar):
            self.solar = solar

        def getSolar(self):
            return self.solar

        def getEightChar(self):
            return FakeEightChar()

    class FakeLunar:
        @staticmethod
        def fromYmdHms(*values):
            return FakeLunarValue(FakeSolarValue(values))

    class FakeDaYun:
        def __init__(self, age, year, ganzhi):
            self.age = age
            self.year = year
            self.ganzhi = ganzhi

        def getStartAge(self):
            return self.age

        def getStartYear(self):
            return self.year

        def getGanZhi(self):
            return self.ganzhi

    class FakeYun:
        def __init__(self, eight_char, gender_code):
            assert isinstance(eight_char, FakeEightChar)
            assert gender_code == 1

        def getDaYun(self):
            return [FakeDaYun(0, 1993, ""), FakeDaYun(8, 2001, "辛亥")]

    monkeypatch.setattr(
        chart_module,
        "_load_lunar_python",
        lambda: (FakeLunar, FakeSolar, FakeYun),
    )
    monkeypatch.setattr(
        chart_module,
        "_provider_version",
        lambda: "lunar-python/test-double",
    )

    chart = build_chart(
        BirthInput(
            local_datetime="1993-03-09 07:00:00",
            longitude=120,
        ),
        "男",
        calculated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    assert chart.four_pillars.hour.ganzhi() == "戊辰"
    assert [period.pillar.ganzhi() for period in chart.dayun] == ["辛亥"]
    assert [warning.code for warning in chart.warnings] == [
        "empty_dayun_period_skipped"
    ]
    assert chart.metadata.provider == "lunar-python/test-double"


def test_build_chart_rejects_invalid_gender_before_provider_load():
    with pytest.raises(ValueError, match="gender must be"):
        build_chart(
            BirthInput(local_datetime="1993-03-09 07:00:00"),
            "未知",
        )
