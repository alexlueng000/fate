from app.chat.consultation import bounded_history, user_facts
from app.services.conversation_report import PERSONAL_TITLES
import pytest


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


@pytest.mark.parametrize('titles', [PERSONAL_TITLES, ['核心观察', '分析依据', '现实建议']])
def test_chapter_questions_keep_the_exact_original_report_outside_recent_window(titles):
    original = {'role': 'assistant', 'content': '\n\n'.join(f'### {title}\n\n原始内容：{title}' for title in titles)}
    question = {'role': 'user', 'content': '最初的问题与出生信息'}
    recent = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': f'后续交流 {i}'} for i in range(20)]
    result = bounded_history([question, original, *recent])
    assert result == [question, original, *recent[-10:]]
    assert user_facts({'taskType': 'career', 'facts': {'topic': question['content']}, 'summary': original['content']}) == {'topic': question['content']}


def test_regenerated_report_does_not_replace_the_readers_first_complete_source():
    original = {'role': 'assistant', 'content': '### 核心观察\n原观察\n### 分析依据\n原依据\n### 现实建议\n原建议'}
    alternative = {'role': 'assistant', 'content': original['content'].replace('原', '替代')}
    question = {'role': 'user', 'content': '原问题'}
    assert bounded_history([question, original, alternative, {'role': 'user', 'content': '报告这节什么意思？'}], 2) == [question, original, alternative, {'role': 'user', 'content': '报告这节什么意思？'}]
    assert bounded_history([question, original]) == [question, original]


def test_incomplete_or_user_supplied_chapters_are_not_promoted_to_saved_ai_report():
    report = '### 核心观察\n观察\n### 分析依据\n依据\n### 现实建议\n建议'
    history = [{'role': 'user', 'content': report}, {'role': 'assistant', 'content': '### 核心观察\n半截'}]
    tail = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': str(i)} for i in range(20)]
    assert bounded_history([*history, *tail]) == [history[0], *tail[-10:]]


@pytest.mark.parametrize('question', ['我想聊感情，适合什么样的伴侣？', '那财运方面呢？', '继续分析事业方向'])
def test_bazi_followups_are_not_bound_to_career_instructions(question):
    from app.chat.consultation import bazi_consultation_context
    class NoCareerLookup:
        def execute(self, *args, **kwargs):
            raise AssertionError('Career instructions must not constrain Bazi follow-ups')
    context = {'taskType': 'career', 'mode': 'bazi', 'facts': {'topic': '是否换工作？', 'currentSituation': '目前有 offer'}}
    history = [{'role': 'user', 'content': '是否换工作？'}, {'role': 'assistant', 'content': '原事业分析'},
               {'role': 'user', 'content': question}]
    messages = bazi_consultation_context(NoCareerLookup(), context, history)
    assert all(message['role'] == 'user' for message in messages)
    assert '仅在当前问题相关时参考' in messages[0]['content']
    assert '目前有 offer' in messages[0]['content']
    assert context['taskType'] == 'career'


def test_bazi_career_opening_and_regeneration_keep_configured_prompt():
    from sqlalchemy import create_engine, text
    from app.chat.consultation import bazi_consultation_context
    engine = create_engine('sqlite://')
    context = {'taskType': 'career', 'facts': {'topic': '是否换工作？'}}
    with engine.begin() as db:
        db.execute(text('CREATE TABLE app_config (cfg_key TEXT, version INTEGER, value_json TEXT, is_active INTEGER)'))
        db.execute(text('INSERT INTO app_config VALUES (:key, 1, :value, 1)'),
                   {'key': 'career_consultation_prompt', 'value': '{"content": "事业首次解读配置"}'})
        for history in ([], [{'role': 'user', 'content': '是否换工作？'}]):
            messages = bazi_consultation_context(db, context, history)
            assert messages[0] == {'role': 'system', 'content': '事业首次解读配置'}
        assert bazi_consultation_context(db, None, []) == []
    engine.dispose()
