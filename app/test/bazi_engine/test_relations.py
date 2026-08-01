import pytest

from app.bazi_engine import FourPillars, Pillar
from app.bazi_engine.relations import (
    BRANCH_BREAKS,
    BRANCH_CLASHES,
    BRANCH_HARMS,
    BRANCH_SIX_COMBINATIONS,
    BRANCH_THREE_HARMONIES,
    BRANCH_THREE_MEETINGS,
    STEM_COMBINATIONS,
    LocatedSymbol,
    RelationType,
    analyze_four_pillars_relations,
    find_branch_relations,
    find_stem_relations,
)


POSITIONS = ("year", "month", "day", "hour")


def located(*symbols):
    return [
        LocatedSymbol(position=position, symbol=symbol)
        for position, symbol in zip(POSITIONS, symbols)
    ]


@pytest.mark.parametrize(("pair", "element"), STEM_COMBINATIONS.items())
def test_all_heavenly_stem_combinations(pair, element):
    left, right = tuple(pair)
    results = find_stem_relations(located(left, right))
    combination = next(
        item for item in results if item.relation == RelationType.STEM_COMBINATION
    )

    assert set(combination.members) == set(pair)
    assert combination.associated_element == element
    assert combination.transformed is None


def test_heavenly_stem_control_is_directional():
    results = find_stem_relations(located("庚", "甲"))

    assert len(results) == 1
    assert results[0].relation == RelationType.STEM_CONTROL
    assert results[0].members == ["庚", "甲"]
    assert results[0].controller_position == "year"
    assert results[0].controlled_position == "month"


@pytest.mark.parametrize(
    ("relation_type", "table"),
    [
        (RelationType.BRANCH_SIX_COMBINATION, BRANCH_SIX_COMBINATIONS),
        (RelationType.BRANCH_CLASH, BRANCH_CLASHES),
        (RelationType.BRANCH_HARM, BRANCH_HARMS),
        (RelationType.BRANCH_BREAK, BRANCH_BREAKS),
    ],
)
def test_all_branch_pair_tables(relation_type, table):
    for pair in table:
        left, right = tuple(pair)
        results = find_branch_relations(located(left, right))
        matches = [item for item in results if item.relation == relation_type]
        assert len(matches) == 1
        assert set(matches[0].members) == set(pair)


@pytest.mark.parametrize(
    ("relation_type", "groups"),
    [
        (RelationType.BRANCH_THREE_HARMONY, BRANCH_THREE_HARMONIES),
        (RelationType.BRANCH_THREE_MEETING, BRANCH_THREE_MEETINGS),
    ],
)
def test_three_branch_groups_distinguish_partial_and_complete(relation_type, groups):
    for group, element in groups.items():
        members = tuple(group)
        partial = find_branch_relations(located(*members[:2]))
        partial_match = next(item for item in partial if item.relation == relation_type)
        assert partial_match.complete is False
        assert partial_match.associated_element == element

        complete = find_branch_relations(located(*members))
        complete_match = next(item for item in complete if item.relation == relation_type)
        assert complete_match.complete is True
        assert set(complete_match.members) == set(group)


@pytest.mark.parametrize(
    ("symbols", "name", "complete"),
    [
        (("寅", "巳"), "无恩之刑", False),
        (("寅", "巳", "申"), "无恩之刑", True),
        (("丑", "未"), "恃势之刑", False),
        (("丑", "未", "戌"), "恃势之刑", True),
        (("子", "卯"), "无礼之刑", True),
    ],
)
def test_branch_punishment_groups(symbols, name, complete):
    results = find_branch_relations(located(*symbols))
    match = next(
        item for item in results if item.relation == RelationType.BRANCH_PUNISHMENT
    )

    assert match.group_name == name
    assert match.complete is complete


@pytest.mark.parametrize("branch", ("辰", "午", "酉", "亥"))
def test_self_punishment_requires_repeated_branch(branch):
    assert not any(
        item.relation == RelationType.BRANCH_SELF_PUNISHMENT
        for item in find_branch_relations(located(branch))
    )

    results = find_branch_relations(located(branch, branch))
    match = next(
        item for item in results if item.relation == RelationType.BRANCH_SELF_PUNISHMENT
    )
    assert match.members == [branch, branch]


def test_four_pillars_analysis_preserves_chart_positions():
    chart = FourPillars(
        year=Pillar(stem="甲", branch="申"),
        month=Pillar(stem="己", branch="子"),
        day=Pillar(stem="庚", branch="辰"),
        hour=Pillar(stem="丁", branch="午"),
    )

    results = analyze_four_pillars_relations(chart)
    stem_combination = next(
        item for item in results if item.relation == RelationType.STEM_COMBINATION
    )
    harmony = next(
        item for item in results if item.relation == RelationType.BRANCH_THREE_HARMONY
    )

    assert stem_combination.positions == ["year", "month"]
    assert harmony.complete is True
    assert set(harmony.positions) == {"year", "month", "day"}
    assert harmony.associated_element == "水"


def test_relation_detector_rejects_invalid_symbols():
    with pytest.raises(ValueError, match="invalid heavenly stem"):
        find_stem_relations(located("木", "甲"))

    with pytest.raises(ValueError, match="invalid earthly branch"):
        find_branch_relations(located("木", "子"))
