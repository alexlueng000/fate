import pytest

from app.bazi_engine.hidden_stems import get_hidden_stems


EXPECTED_HIDDEN_STEMS = {
    "子": [("癸", "本气")],
    "丑": [("己", "本气"), ("癸", "中气"), ("辛", "余气")],
    "寅": [("甲", "本气"), ("丙", "中气"), ("戊", "余气")],
    "卯": [("乙", "本气")],
    "辰": [("戊", "本气"), ("乙", "中气"), ("癸", "余气")],
    "巳": [("丙", "本气"), ("戊", "中气"), ("庚", "余气")],
    "午": [("丁", "本气"), ("己", "中气")],
    "未": [("己", "本气"), ("丁", "中气"), ("乙", "余气")],
    "申": [("庚", "本气"), ("壬", "中气"), ("戊", "余气")],
    "酉": [("辛", "本气")],
    "戌": [("戊", "本气"), ("辛", "中气"), ("丁", "余气")],
    "亥": [("壬", "本气"), ("甲", "中气")],
}


@pytest.mark.parametrize(("branch", "expected"), EXPECTED_HIDDEN_STEMS.items())
def test_all_twelve_branch_hidden_stems(branch, expected):
    actual = get_hidden_stems(branch)

    assert [(item.stem, item.role) for item in actual] == expected
    assert all(item.element in "木火土金水" for item in actual)
    assert all(item.polarity in ("阳", "阴") for item in actual)


def test_hidden_stems_reject_invalid_branch():
    with pytest.raises(ValueError, match="invalid earthly branch"):
        get_hidden_stems("甲")
