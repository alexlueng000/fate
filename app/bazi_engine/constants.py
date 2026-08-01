"""Canonical stem, branch, element, polarity, and hidden-stem tables."""

from typing import Final, Literal


Element = Literal["木", "火", "土", "金", "水"]
Polarity = Literal["阳", "阴"]
HiddenStemRole = Literal["本气", "中气", "余气"]

HEAVENLY_STEMS: Final[tuple[str, ...]] = tuple("甲乙丙丁戊己庚辛壬癸")
EARTHLY_BRANCHES: Final[tuple[str, ...]] = tuple("子丑寅卯辰巳午未申酉戌亥")

STEM_ELEMENT: Final[dict[str, Element]] = {
    "甲": "木",
    "乙": "木",
    "丙": "火",
    "丁": "火",
    "戊": "土",
    "己": "土",
    "庚": "金",
    "辛": "金",
    "壬": "水",
    "癸": "水",
}

STEM_POLARITY: Final[dict[str, Polarity]] = {
    "甲": "阳",
    "乙": "阴",
    "丙": "阳",
    "丁": "阴",
    "戊": "阳",
    "己": "阴",
    "庚": "阳",
    "辛": "阴",
    "壬": "阳",
    "癸": "阴",
}

BRANCH_ELEMENT: Final[dict[str, Element]] = {
    "子": "水",
    "丑": "土",
    "寅": "木",
    "卯": "木",
    "辰": "土",
    "巳": "火",
    "午": "火",
    "未": "土",
    "申": "金",
    "酉": "金",
    "戌": "土",
    "亥": "水",
}

BRANCH_POLARITY: Final[dict[str, Polarity]] = {
    "子": "阳",
    "丑": "阴",
    "寅": "阳",
    "卯": "阴",
    "辰": "阳",
    "巳": "阴",
    "午": "阳",
    "未": "阴",
    "申": "阳",
    "酉": "阴",
    "戌": "阳",
    "亥": "阴",
}

# Ordered from dominant qi to secondary/residual qi. The role is explicit so
# future strength calculations do not need to infer meaning from list indexes.
BRANCH_HIDDEN_STEMS: Final[dict[str, tuple[tuple[str, HiddenStemRole], ...]]] = {
    "子": (("癸", "本气"),),
    "丑": (("己", "本气"), ("癸", "中气"), ("辛", "余气")),
    "寅": (("甲", "本气"), ("丙", "中气"), ("戊", "余气")),
    "卯": (("乙", "本气"),),
    "辰": (("戊", "本气"), ("乙", "中气"), ("癸", "余气")),
    "巳": (("丙", "本气"), ("戊", "中气"), ("庚", "余气")),
    "午": (("丁", "本气"), ("己", "中气")),
    "未": (("己", "本气"), ("丁", "中气"), ("乙", "余气")),
    "申": (("庚", "本气"), ("壬", "中气"), ("戊", "余气")),
    "酉": (("辛", "本气"),),
    "戌": (("戊", "本气"), ("辛", "中气"), ("丁", "余气")),
    "亥": (("壬", "本气"), ("甲", "中气")),
}

GENERATES: Final[dict[Element, Element]] = {
    "木": "火",
    "火": "土",
    "土": "金",
    "金": "水",
    "水": "木",
}

CONTROLS: Final[dict[Element, Element]] = {
    "木": "土",
    "火": "金",
    "土": "水",
    "金": "木",
    "水": "火",
}
