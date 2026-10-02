"""Offline response checks. Input JSON maps case ids to real model response strings.
This does not call a provider or claim to evaluate metaphysical accuracy.
Manual semantic review remains required against each case's review checklist.
"""
import argparse
import json
import re
from pathlib import Path

CASES = Path(__file__).resolve().parents[1] / 'evals' / 'consultation_cases.json'


def evaluate(case, response):
    issues = []
    if not isinstance(response, str) or not response.strip():
        return ['missing_response']
    headings = re.findall(r'^###\s+(.+?)\s*$', response, re.M)
    expected = ['核心观察', '分析依据', '现实建议']
    if case['shape'] == 'initial' and headings != expected:
        issues.append('initial_sections')
    if case['shape'] != 'initial' and headings == expected:
        issues.append('unnecessary_full_report')
    if re.search(r'^#{1,2}\s|^#{5,}\s', response, re.M):
        issues.append('heading_level')
    match = re.search(r'---SUGGESTED_QUESTIONS---(.*?)---END_SUGGESTED_QUESTIONS---', response, re.S)
    if match and len([line for line in match[1].splitlines() if line.strip()]) > 3:
        issues.append('too_many_suggestions')
    if '---SUGGESTED_QUESTIONS---' in response and not match:
        issues.append('truncated_suggestions')
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('responses', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    responses = json.loads(args.responses.read_text())
    results = [{'id': case['id'], 'issues': evaluate(case, responses.get(case['id'])),
                'manual_review_required': case['review']} for case in json.loads(CASES.read_text())]
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    raise SystemExit(1 if any(item['issues'] for item in results) else 0)


if __name__ == '__main__':
    main()
