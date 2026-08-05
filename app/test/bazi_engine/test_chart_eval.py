from datetime import datetime
from pathlib import Path

from app.bazi_engine import BirthInput, chart_from_legacy_paipan
from app.evals.chart_eval import evaluate_chart_cases
from app.evals.loaders import load_chart_cases
from app.evals.schemas import ChartGoldenCase, GoldenStatus


DATASET = (
    Path(__file__).parents[2]
    / "evals"
    / "datasets"
    / "chart"
    / "ordinary.json"
)


def fake_chart(*, hour="戊辰", adjusted="1993-03-09 07:00:00"):
    return chart_from_legacy_paipan(
        {
            "gender": "男",
            "solar_date": adjusted,
            "four_pillars": {
                "year": "癸酉",
                "month": "乙卯",
                "day": "己丑",
                "hour": hour,
            },
            "dayun": [],
        },
        birth=BirthInput(local_datetime=adjusted),
    )


def verified_case() -> ChartGoldenCase:
    return ChartGoldenCase.model_validate(
        {
            "case_id": "verified_001",
            "description": "评测器测试案例",
            "gender": "男",
            "input": {
                "local_datetime": "1993-03-09 07:00:00",
                "longitude": 120
            },
            "expected": {
                "adjusted_datetime": "1993-03-09 07:00:00",
                "four_pillars": {
                    "year": "癸酉",
                    "month": "乙卯",
                    "day": "己丑",
                    "hour": "戊辰"
                }
            },
            "provenance": {
                "status": "verified",
                "sources": ["test-source-a", "test-source-b"]
            }
        }
    )


def test_release_evaluation_skips_candidate_cases_by_default():
    report = evaluate_chart_cases(load_chart_cases(DATASET), builder=lambda *a, **k: fake_chart())

    assert report.total == 5
    assert report.eligible == 0
    assert report.skipped == 5
    assert report.pass_rate == 0


def test_evaluation_reports_pass_and_precise_difference():
    case = verified_case()

    passing = evaluate_chart_cases([case], builder=lambda *a, **k: fake_chart())
    assert passing.passed == 1
    assert passing.pass_rate == 100

    failing = evaluate_chart_cases(
        [case],
        builder=lambda *a, **k: fake_chart(hour="己巳"),
    )
    assert failing.failed == 1
    assert failing.results[0].differences[0].field == "four_pillars.hour"
    assert failing.results[0].differences[0].expected == "戊辰"
    assert failing.results[0].differences[0].actual == "己巳"


def test_candidate_cases_can_be_enabled_explicitly():
    cases = load_chart_cases(DATASET)

    def candidate_builder(birth, gender, *, options):
        return fake_chart(adjusted=birth.local_datetime.isoformat(sep=" "))

    report = evaluate_chart_cases(
        cases,
        builder=candidate_builder,
        included_statuses={GoldenStatus.CANDIDATE},
    )

    assert report.eligible == 5
    assert report.passed == 5
    assert report.pass_rate == 100


def test_builder_error_is_captured_without_stopping_other_cases():
    case = verified_case()

    report = evaluate_chart_cases(
        [case],
        builder=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert report.errors == 1
    assert report.results[0].outcome == "error"
    assert report.results[0].reason == "RuntimeError: boom"
