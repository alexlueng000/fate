"""Deterministic Ten Gods calculation relative to a day master."""

from __future__ import annotations

from enum import Enum
from typing import List

from .constants import (
    CONTROLS,
    GENERATES,
    HEAVENLY_STEMS,
    STEM_ELEMENT,
    STEM_POLARITY,
    Element,
    Polarity,
)
from .hidden_stems import get_hidden_stems
from .schemas import Pillar, StrictModel


class TenGod(str, Enum):
    BI_JIAN = "比肩"
    JIE_CAI = "劫财"
    SHI_SHEN = "食神"
    SHANG_GUAN = "伤官"
    PIAN_CAI = "偏财"
    ZHENG_CAI = "正财"
    QI_SHA = "七杀"
    ZHENG_GUAN = "正官"
    PIAN_YIN = "偏印"
    ZHENG_YIN = "正印"


class TenGodResult(StrictModel):
    day_master: str
    target_stem: str
    name: TenGod
    element: Element
    polarity: Polarity


class HiddenStemTenGod(StrictModel):
    stem: str
    role: str
    ten_god: TenGodResult


class PillarTenGodAnalysis(StrictModel):
    stem: TenGodResult
    hidden_stems: List[HiddenStemTenGod]


def calculate_ten_god(day_master: str, target_stem: str) -> TenGodResult:
    """Calculate the target stem's Ten God relative to ``day_master``."""

    if day_master not in HEAVENLY_STEMS:
        raise ValueError(f"invalid day master: {day_master}")
    if target_stem not in HEAVENLY_STEMS:
        raise ValueError(f"invalid target stem: {target_stem}")

    day_element = STEM_ELEMENT[day_master]
    target_element = STEM_ELEMENT[target_stem]
    same_polarity = STEM_POLARITY[day_master] == STEM_POLARITY[target_stem]

    if target_element == day_element:
        name = TenGod.BI_JIAN if same_polarity else TenGod.JIE_CAI
    elif GENERATES[day_element] == target_element:
        name = TenGod.SHI_SHEN if same_polarity else TenGod.SHANG_GUAN
    elif CONTROLS[day_element] == target_element:
        name = TenGod.PIAN_CAI if same_polarity else TenGod.ZHENG_CAI
    elif CONTROLS[target_element] == day_element:
        name = TenGod.QI_SHA if same_polarity else TenGod.ZHENG_GUAN
    elif GENERATES[target_element] == day_element:
        name = TenGod.PIAN_YIN if same_polarity else TenGod.ZHENG_YIN
    else:  # Defensive guard if the five-element tables become incomplete.
        raise ValueError(
            f"unable to determine element relationship: {day_element}/{target_element}"
        )

    return TenGodResult(
        day_master=day_master,
        target_stem=target_stem,
        name=name,
        element=target_element,
        polarity=STEM_POLARITY[target_stem],
    )


def analyze_pillar_ten_gods(
    day_master: str,
    pillar: Pillar,
) -> PillarTenGodAnalysis:
    """Calculate Ten Gods for a visible stem and all stems hidden in its branch."""

    hidden_results = [
        HiddenStemTenGod(
            stem=hidden.stem,
            role=hidden.role,
            ten_god=calculate_ten_god(day_master, hidden.stem),
        )
        for hidden in get_hidden_stems(pillar.branch)
    ]
    return PillarTenGodAnalysis(
        stem=calculate_ten_god(day_master, pillar.stem),
        hidden_stems=hidden_results,
    )
