"""Load and validate golden cases from JSON datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from .schemas import ChartGoldenCase


def load_chart_cases(path: str | Path) -> List[ChartGoldenCase]:
    """Load a JSON list or ``{"cases": [...]}`` document."""

    dataset_path = Path(path)
    with dataset_path.open("r", encoding="utf-8") as file:
        raw = json.load(file)

    items = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(f"chart dataset must contain a list: {dataset_path}")
    cases = [ChartGoldenCase.model_validate(item) for item in items]
    _ensure_unique_case_ids(cases, source=str(dataset_path))
    return cases


def load_chart_case_files(paths: Iterable[str | Path]) -> List[ChartGoldenCase]:
    """Load multiple dataset files and enforce globally unique case IDs."""

    cases = [case for path in paths for case in load_chart_cases(path)]
    _ensure_unique_case_ids(cases, source="combined chart datasets")
    return cases


def _ensure_unique_case_ids(cases: Iterable[ChartGoldenCase], *, source: str) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise ValueError(f"duplicate case_id {case.case_id!r} in {source}")
        seen.add(case.case_id)

