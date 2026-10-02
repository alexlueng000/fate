from app.chat.consultation import bounded_history, user_facts


def test_preserves_original_user_question_outside_recent_window():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(20)]
    result = bounded_history(history)
    assert result[0] == history[0]
    assert result[1:] == history[-10:]


def test_assistant_claims_never_become_user_facts():
    context = {"taskType": "career", "summary": "用户必然升职", "facts": {"topic": "换工作？", "currentSituation": "  有 offer  ", "summary": "预测", "options": ["not text"]}}
    assert user_facts(context) == {"topic": "换工作？", "currentSituation": "有 offer"}
    assert user_facts({"taskType": "career", "summary": "should not inject"}) == {}


def test_context_is_bounded_and_old_non_career_context_is_compatible():
    assert len(user_facts({"taskType": "career", "facts": {"topic": "字" * 1000}})["topic"]) == 400
    assert user_facts(None) == {}
    assert bounded_history([]) == []
    assert bounded_history([{"role": "system", "content": "untrusted"}]) == []


def test_liuyao_prompt_keeps_computed_line_details():
    from types import SimpleNamespace
    from app.liuyao.prompts import build_hexagram_context
    hexagram = SimpleNamespace(gender='unknown', ganzhi={}, jiqi={}, question='机会', main_gua='乾', change_gua='姤',
        shi_yao=6, ying_yao=3, gua_shen=None, shensha=None, lunar_date=None,
        lines={'lines': [{'is_dong': True, 'dizhi': '子', 'liuqin': '子孙'}]},
        change_lines={'lines': [{'is_dong': False, 'dizhi': '丑'}]})
    result = build_hexagram_context(hexagram)
    assert '子孙' in result and '"dizhi": "子"' in result
    assert '变卦六爻' in result and '"dizhi": "丑"' in result
