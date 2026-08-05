from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evals.loaders import load_chart_case_files, load_chart_cases
from app.evals.schemas import ChartGoldenCase, GoldenStatus


DATASET = (
    Path(__file__).parents[2]
    / "evals"
    / "datasets"
    / "chart"
    / "ordinary.json"
)


def test_candidate_dataset_loads_and_has_unique_ids():
    cases = load_chart_cases(DATASET)

    assert len(cases) == 5
    assert len({case.case_id for case in cases}) == 5
    assert {case.provenance.status for case in cases} == {GoldenStatus.CANDIDATE}


def test_combined_loader_rejects_duplicate_case_ids():
    with pytest.raises(ValueError, match="duplicate case_id"):
        load_chart_case_files([DATASET, DATASET])


def test_verified_case_requires_four_pillars():
    raw = load_chart_cases(DATASET)[0].model_dump(mode="json")
    raw["provenance"]["status"] = "verified"

    with pytest.raises(ValidationError, match="require four_pillars"):
        ChartGoldenCase.model_validate(raw)


def test_approved_case_requires_reviewer():
    raw = load_chart_cases(DATASET)[0].model_dump(mode="json")
    raw["provenance"]["status"] = "approved"
    raw["expected"]["four_pillars"] = {
        "year": "癸酉",
        "month": "乙卯",
        "day": "己丑",
        "hour": "戊辰",
    }

    with pytest.raises(ValidationError, match="reviewed_by"):
        ChartGoldenCase.model_validate(raw)

