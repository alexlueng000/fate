from scripts.evaluate_consultation import evaluate


def test_initial_and_followup_shape_are_different():
    response = '### 核心观察\n观察\n### 分析依据\n依据\n### 现实建议\n行动'
    assert evaluate({'shape': 'initial'}, response) == []
    assert evaluate({'shape': 'follow_up'}, response) == ['unnecessary_full_report']
    assert evaluate({'shape': 'clarification'}, '你主要想讨论哪个具体机会？') == []


def test_missing_and_truncated_answers_cannot_pass():
    assert evaluate({'shape': 'initial'}, None) == ['missing_response']
    assert evaluate({'shape': 'follow_up'}, '回复\n---SUGGESTED_QUESTIONS---\n问题') == ['truncated_suggestions']
