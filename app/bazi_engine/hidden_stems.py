"""Deterministic hidden-stem lookup for the twelve earthly branches."""

from __future__ import annotations

from typing import List

from pydantic import Field

from .constants import (
    BRANCH_HIDDEN_STEMS,
    EARTHLY_BRANCHES,
    STEM_ELEMENT,
    STEM_POLARITY,
    Element,
    HiddenStemRole,
    Polarity,
)
from .schemas import StrictModel


class HiddenStem(StrictModel):
    stem: str = Field(min_length=1, max_length=1)
    role: HiddenStemRole
    element: Element
    polarity: Polarity


def get_hidden_stems(branch: str) -> List[HiddenStem]:
    """Return hidden stems in dominant-to-residual order for ``branch``."""

    if branch not in EARTHLY_BRANCHES:
        raise ValueError(f"invalid earthly branch: {branch}")

    return [
        HiddenStem(
            stem=stem,
            role=role,
            element=STEM_ELEMENT[stem],
            polarity=STEM_POLARITY[stem],
        )
        for stem, role in BRANCH_HIDDEN_STEMS[branch]
    ]
