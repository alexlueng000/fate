import pytest

from app.bazi_engine import Pillar
from app.bazi_engine.constants import HEAVENLY_STEMS
from app.bazi_engine.ten_gods import (
    TenGod,
    analyze_pillar_ten_gods,
    calculate_ten_god,
)


# Rows are day masters; columns follow 甲乙丙丁戊己庚辛壬癸.
EXPECTED_MATRIX = {
    "甲": "比肩 劫财 食神 伤官 偏财 正财 七杀 正官 偏印 正印",
    "乙": "劫财 比肩 伤官 食神 正财 偏财 正官 七杀 正印 偏印",
    "丙": "偏印 正印 比肩 劫财 食神 伤官 偏财 正财 七杀 正官",
    "丁": "正印 偏印 劫财 比肩 伤官 食神 正财 偏财 正官 七杀",
    "戊": "七杀 正官 偏印 正印 比肩 劫财 食神 伤官 偏财 正财",
    "己": "正官 七杀 正印 偏印 劫财 比肩 伤官 食神 正财 偏财",
    "庚": "偏财 正财 七杀 正官 偏印 正印 比肩 劫财 食神 伤官",
    "辛": "正财 偏财 正官 七杀 正印 偏印 劫财 比肩 伤官 食神",
    "壬": "食神 伤官 偏财 正财 七杀 正官 偏印 正印 比肩 劫财",
    "癸": "伤官 食神 正财 偏财 正官 七杀 正印 偏印 劫财 比肩",
}


@pytest.mark.parametrize("day_master", HEAVENLY_STEMS)
def test_complete_ten_gods_matrix(day_master):
    expected = EXPECTED_MATRIX[day_master].split()
    actual = [
        calculate_ten_god(day_master, target).name.value
        for target in HEAVENLY_STEMS
    ]

    assert actual == expected


def test_each_day_master_maps_to_all_ten_gods_once():
    expected = set(TenGod)
    for day_master in HEAVENLY_STEMS:
        actual = {
            calculate_ten_god(day_master, target).name
            for target in HEAVENLY_STEMS
        }
        assert actual == expected


def test_pillar_analysis_includes_visible_and_hidden_stems():
    result = analyze_pillar_ten_gods("甲", Pillar(stem="庚", branch="丑"))

    assert result.stem.name == TenGod.QI_SHA
    assert [item.stem for item in result.hidden_stems] == ["己", "癸", "辛"]
    assert [item.ten_god.name for item in result.hidden_stems] == [
        TenGod.ZHENG_CAI,
        TenGod.ZHENG_YIN,
        TenGod.ZHENG_GUAN,
    ]


@pytest.mark.parametrize(
    ("day_master", "target", "message"),
    [
        ("木", "甲", "invalid day master"),
        ("甲", "木", "invalid target stem"),
    ],
)
def test_ten_gods_reject_invalid_stems(day_master, target, message):
    with pytest.raises(ValueError, match=message):
        calculate_ten_god(day_master, target)
