"""Deterministic relationship detection between visible stems and branches.

This module detects structural relationships only. It deliberately does not
decide whether a combination transforms, whether a clash is auspicious, or how
strong a relationship is; those decisions require season, rooting, exposure,
and other chart evidence handled by later engine stages.
"""

from __future__ import annotations

from enum import Enum
from itertools import combinations
from typing import List, Literal, Optional, Sequence

from pydantic import Field

from .constants import (
    CONTROLS,
    EARTHLY_BRANCHES,
    HEAVENLY_STEMS,
    STEM_ELEMENT,
    Element,
)
from .schemas import FourPillars, StrictModel


ChartPosition = Literal["year", "month", "day", "hour"]
RelationScope = Literal["stem", "branch"]


class RelationType(str, Enum):
    STEM_COMBINATION = "天干五合"
    STEM_CONTROL = "天干相克"
    BRANCH_SIX_COMBINATION = "地支六合"
    BRANCH_CLASH = "地支六冲"
    BRANCH_HARM = "地支六害"
    BRANCH_BREAK = "地支六破"
    BRANCH_THREE_HARMONY = "地支三合"
    BRANCH_THREE_MEETING = "地支三会"
    BRANCH_PUNISHMENT = "地支相刑"
    BRANCH_SELF_PUNISHMENT = "地支自刑"


class LocatedSymbol(StrictModel):
    position: ChartPosition
    symbol: str = Field(min_length=1, max_length=1)


class GanzhiRelation(StrictModel):
    relation: RelationType
    scope: RelationScope
    members: List[str] = Field(min_length=2)
    positions: List[ChartPosition] = Field(min_length=2)
    complete: bool = True
    associated_element: Optional[Element] = None
    transformed: Optional[bool] = None
    controller_position: Optional[ChartPosition] = None
    controlled_position: Optional[ChartPosition] = None
    group_name: Optional[str] = None


STEM_COMBINATIONS: dict[frozenset[str], Element] = {
    frozenset(("甲", "己")): "土",
    frozenset(("乙", "庚")): "金",
    frozenset(("丙", "辛")): "水",
    frozenset(("丁", "壬")): "木",
    frozenset(("戊", "癸")): "火",
}

BRANCH_SIX_COMBINATIONS: dict[frozenset[str], Element] = {
    frozenset(("子", "丑")): "土",
    frozenset(("寅", "亥")): "木",
    frozenset(("卯", "戌")): "火",
    frozenset(("辰", "酉")): "金",
    frozenset(("巳", "申")): "水",
    frozenset(("午", "未")): "土",
}

BRANCH_CLASHES = frozenset(
    frozenset(pair)
    for pair in (("子", "午"), ("丑", "未"), ("寅", "申"), ("卯", "酉"), ("辰", "戌"), ("巳", "亥"))
)

BRANCH_HARMS = frozenset(
    frozenset(pair)
    for pair in (("子", "未"), ("丑", "午"), ("寅", "巳"), ("卯", "辰"), ("申", "亥"), ("酉", "戌"))
)

BRANCH_BREAKS = frozenset(
    frozenset(pair)
    for pair in (("子", "酉"), ("丑", "辰"), ("寅", "亥"), ("卯", "午"), ("巳", "申"), ("未", "戌"))
)

BRANCH_THREE_HARMONIES: dict[frozenset[str], Element] = {
    frozenset(("申", "子", "辰")): "水",
    frozenset(("亥", "卯", "未")): "木",
    frozenset(("寅", "午", "戌")): "火",
    frozenset(("巳", "酉", "丑")): "金",
}

BRANCH_THREE_MEETINGS: dict[frozenset[str], Element] = {
    frozenset(("寅", "卯", "辰")): "木",
    frozenset(("巳", "午", "未")): "火",
    frozenset(("申", "酉", "戌")): "金",
    frozenset(("亥", "子", "丑")): "水",
}

# The two three-member groups can be detected as partial (two present) or
# complete (all three present). 子卯 is a complete two-member punishment.
BRANCH_PUNISHMENT_GROUPS: dict[str, frozenset[str]] = {
    "无恩之刑": frozenset(("寅", "巳", "申")),
    "恃势之刑": frozenset(("丑", "未", "戌")),
    "无礼之刑": frozenset(("子", "卯")),
}

SELF_PUNISHMENT_BRANCHES = frozenset(("辰", "午", "酉", "亥"))


def _pair_relation(
    relation: RelationType,
    left: LocatedSymbol,
    right: LocatedSymbol,
    *,
    scope: RelationScope,
    associated_element: Optional[Element] = None,
) -> GanzhiRelation:
    return GanzhiRelation(
        relation=relation,
        scope=scope,
        members=[left.symbol, right.symbol],
        positions=[left.position, right.position],
        associated_element=associated_element,
    )


def find_stem_relations(stems: Sequence[LocatedSymbol]) -> List[GanzhiRelation]:
    """Find combinations and directional controls among visible stems."""

    invalid = [item.symbol for item in stems if item.symbol not in HEAVENLY_STEMS]
    if invalid:
        raise ValueError(f"invalid heavenly stem: {invalid[0]}")

    results: List[GanzhiRelation] = []
    for left, right in combinations(stems, 2):
        pair = frozenset((left.symbol, right.symbol))
        if pair in STEM_COMBINATIONS:
            results.append(
                _pair_relation(
                    RelationType.STEM_COMBINATION,
                    left,
                    right,
                    scope="stem",
                    associated_element=STEM_COMBINATIONS[pair],
                )
            )

        left_element = STEM_ELEMENT[left.symbol]
        right_element = STEM_ELEMENT[right.symbol]
        if CONTROLS[left_element] == right_element:
            controller, controlled = left, right
        elif CONTROLS[right_element] == left_element:
            controller, controlled = right, left
        else:
            continue
        results.append(
            GanzhiRelation(
                relation=RelationType.STEM_CONTROL,
                scope="stem",
                members=[controller.symbol, controlled.symbol],
                positions=[controller.position, controlled.position],
                controller_position=controller.position,
                controlled_position=controlled.position,
            )
        )
    return results


def _find_branch_pairs(branches: Sequence[LocatedSymbol]) -> List[GanzhiRelation]:
    results: List[GanzhiRelation] = []
    pair_tables = (
        (RelationType.BRANCH_SIX_COMBINATION, BRANCH_SIX_COMBINATIONS),
        (RelationType.BRANCH_CLASH, BRANCH_CLASHES),
        (RelationType.BRANCH_HARM, BRANCH_HARMS),
        (RelationType.BRANCH_BREAK, BRANCH_BREAKS),
    )
    for left, right in combinations(branches, 2):
        pair = frozenset((left.symbol, right.symbol))
        for relation, table in pair_tables:
            if pair not in table:
                continue
            element = table[pair] if isinstance(table, dict) else None
            results.append(
                _pair_relation(
                    relation,
                    left,
                    right,
                    scope="branch",
                    associated_element=element,
                )
            )
    return results


def _find_branch_groups(
    branches: Sequence[LocatedSymbol],
    groups: dict[frozenset[str], Element],
    relation: RelationType,
) -> List[GanzhiRelation]:
    results: List[GanzhiRelation] = []
    for group, element in groups.items():
        matched = [item for item in branches if item.symbol in group]
        distinct = {item.symbol for item in matched}
        if len(distinct) < 2:
            continue
        # Retain one position for each distinct member. Repeated branches do not
        # make a three-member group complete.
        selected: List[LocatedSymbol] = []
        seen: set[str] = set()
        for item in matched:
            if item.symbol not in seen:
                selected.append(item)
                seen.add(item.symbol)
        results.append(
            GanzhiRelation(
                relation=relation,
                scope="branch",
                members=[item.symbol for item in selected],
                positions=[item.position for item in selected],
                complete=distinct == set(group),
                associated_element=element,
            )
        )
    return results


def _find_branch_punishments(
    branches: Sequence[LocatedSymbol],
) -> List[GanzhiRelation]:
    results: List[GanzhiRelation] = []
    for name, group in BRANCH_PUNISHMENT_GROUPS.items():
        matched = [item for item in branches if item.symbol in group]
        distinct = {item.symbol for item in matched}
        if len(distinct) < 2:
            continue
        selected: List[LocatedSymbol] = []
        seen: set[str] = set()
        for item in matched:
            if item.symbol not in seen:
                selected.append(item)
                seen.add(item.symbol)
        results.append(
            GanzhiRelation(
                relation=RelationType.BRANCH_PUNISHMENT,
                scope="branch",
                members=[item.symbol for item in selected],
                positions=[item.position for item in selected],
                complete=distinct == set(group),
                group_name=name,
            )
        )

    for branch in SELF_PUNISHMENT_BRANCHES:
        matched = [item for item in branches if item.symbol == branch]
        if len(matched) >= 2:
            results.append(
                GanzhiRelation(
                    relation=RelationType.BRANCH_SELF_PUNISHMENT,
                    scope="branch",
                    members=[item.symbol for item in matched],
                    positions=[item.position for item in matched],
                    group_name="自刑",
                )
            )
    return results


def find_branch_relations(branches: Sequence[LocatedSymbol]) -> List[GanzhiRelation]:
    """Find pair, group, punishment, and self-punishment relationships."""

    invalid = [item.symbol for item in branches if item.symbol not in EARTHLY_BRANCHES]
    if invalid:
        raise ValueError(f"invalid earthly branch: {invalid[0]}")

    return [
        *_find_branch_pairs(branches),
        *_find_branch_groups(
            branches,
            BRANCH_THREE_HARMONIES,
            RelationType.BRANCH_THREE_HARMONY,
        ),
        *_find_branch_groups(
            branches,
            BRANCH_THREE_MEETINGS,
            RelationType.BRANCH_THREE_MEETING,
        ),
        *_find_branch_punishments(branches),
    ]


def analyze_four_pillars_relations(
    four_pillars: FourPillars,
) -> List[GanzhiRelation]:
    """Detect all structural relationships in a natal Four Pillars chart."""

    positioned = [
        ("year", four_pillars.year),
        ("month", four_pillars.month),
        ("day", four_pillars.day),
        ("hour", four_pillars.hour),
    ]
    stems = [
        LocatedSymbol(position=position, symbol=pillar.stem)
        for position, pillar in positioned
    ]
    branches = [
        LocatedSymbol(position=position, symbol=pillar.branch)
        for position, pillar in positioned
    ]
    return [*find_stem_relations(stems), *find_branch_relations(branches)]
