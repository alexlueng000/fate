"""Offline comparison runner for Bazi chart golden datasets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, Iterable, Sequence

from app.bazi_engine import BaziChart, build_chart

from .loaders import load_chart_case_files
from .schemas import (
    CaseEvaluationResult,
    ChartEvaluationReport,
    ChartGoldenCase,
    EvaluationDifference,
    GoldenStatus,
)


ChartBuilder = Callable[..., BaziChart]
RELEASE_STATUSES = frozenset((GoldenStatus.VERIFIED, GoldenStatus.APPROVED))


def _compare_case(case: ChartGoldenCase, actual: BaziChart) -> list[EvaluationDifference]:
    differences: list[EvaluationDifference] = []
    expected = case.expected

    if expected.adjusted_datetime is not None:
        if actual.adjusted_datetime != expected.adjusted_datetime:
            differences.append(
                EvaluationDifference(
                    field="adjusted_datetime",
                    expected=expected.adjusted_datetime.isoformat(sep=" "),
                    actual=actual.adjusted_datetime.isoformat(sep=" "),
                )
            )

    if expected.four_pillars is not None:
        expected_pillars = expected.four_pillars.model_dump()
        actual_pillars = {
            position: getattr(actual.four_pillars, position).ganzhi()
            for position in ("year", "month", "day", "hour")
        }
        for position in ("year", "month", "day", "hour"):
            if actual_pillars[position] != expected_pillars[position]:
                differences.append(
                    EvaluationDifference(
                        field=f"four_pillars.{position}",
                        expected=expected_pillars[position],
                        actual=actual_pillars[position],
                    )
                )

    if expected.dayun is not None:
        expected_dayun = [
            {
                "start_age": item.start_age,
                "start_year": item.start_year,
                "pillar": item.pillar,
            }
            for item in expected.dayun
        ]
        actual_dayun = [
            {
                "start_age": item.start_age,
                "start_year": item.start_year,
                "pillar": item.pillar.ganzhi(),
            }
            for item in actual.dayun
        ]
        if actual_dayun != expected_dayun:
            differences.append(
                EvaluationDifference(
                    field="dayun",
                    expected=expected_dayun,
                    actual=actual_dayun,
                )
            )
    return differences


def evaluate_chart_cases(
    cases: Sequence[ChartGoldenCase],
    *,
    builder: ChartBuilder = build_chart,
    included_statuses: Iterable[GoldenStatus] = RELEASE_STATUSES,
) -> ChartEvaluationReport:
    """Evaluate cases without changing expected data on failure."""

    allowed = set(included_statuses)
    results: list[CaseEvaluationResult] = []
    eligible = 0
    for case in cases:
        if case.provenance.status not in allowed:
            results.append(
                CaseEvaluationResult(
                    case_id=case.case_id,
                    outcome="skipped",
                    reason=f"status={case.provenance.status.value} is not enabled",
                )
            )
            continue

        eligible += 1
        try:
            actual = builder(case.input, case.gender, options=case.options)
            differences = _compare_case(case, actual)
            results.append(
                CaseEvaluationResult(
                    case_id=case.case_id,
                    outcome="failed" if differences else "passed",
                    differences=differences,
                )
            )
        except Exception as exc:
            results.append(
                CaseEvaluationResult(
                    case_id=case.case_id,
                    outcome="error",
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )

    passed = sum(item.outcome == "passed" for item in results)
    failed = sum(item.outcome == "failed" for item in results)
    skipped = sum(item.outcome == "skipped" for item in results)
    errors = sum(item.outcome == "error" for item in results)
    return ChartEvaluationReport(
        total=len(cases),
        eligible=eligible,
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        pass_rate=round(passed / eligible * 100, 2) if eligible else 0.0,
        results=results,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Bazi chart golden datasets")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--include-candidates",
        action="store_true",
        help="Run candidate cases in addition to release-gating goldens",
    )
    args = parser.parse_args()
    statuses = set(RELEASE_STATUSES)
    if args.include_candidates:
        statuses.add(GoldenStatus.CANDIDATE)
    report = evaluate_chart_cases(
        load_chart_case_files(args.paths),
        included_statuses=statuses,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 1 if report.failed or report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

