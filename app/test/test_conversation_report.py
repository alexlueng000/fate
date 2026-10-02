"""Persisted report HTTP contract. SQLite durability; no model quality claim."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.deps import get_current_user_or_401
from app.models.chat import Conversation, Message
from app.models.profile import UserProfile
from app.models.conversation_digest import ConversationDigest
from app.models.message_rating import MessageRating
from app.models.quota import UserQuota
from app.routers.conversations import router
from app.services.conversation_report import report_sections, PERSONAL_TITLES

REPORT = "### 核心观察\n\n先明确工作内容。\n\n### 分析依据\n\n用户只提供了工作稳定这一背景。\n\n### 现实建议\n\n向招聘方核对岗位职责，收到书面说明后再复盘。"


@pytest.fixture
def saved(tmp_path):
    url = f"sqlite:///{tmp_path / 'reports.sqlite'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    for model in (UserProfile, Conversation, Message, ConversationDigest, MessageRating, UserQuota):
        model.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE app_config (cfg_key TEXT, value_json TEXT, is_active INTEGER, version INTEGER)'))
    sessions = sessionmaker(engine)
    chart = {"mingpan": {"four_pillars": {"year": ["甲", "子"]}}}
    context = {"taskType": "career", "facts": {"topic": "如何选择职业方向？", "currentSituation": "工作稳定", "summary": "我会升职"}}
    with sessions() as db:
        db.add(Conversation(id=1, user_id=1, profile_id=1, title="事业咨询", bazi_chart_snapshot=chart, task_context=context))
        db.add_all([
            Message(id=1, conversation_id=1, user_id=1, role="user", content="如何选择职业方向？"),
            Message(id=2, conversation_id=1, user_id=1, role="assistant", content="请补充你目前的工作情况。"),
            Message(id=3, conversation_id=1, user_id=1, role="user", content="工作稳定"),
            Message(id=4, conversation_id=1, user_id=1, role="assistant", content=REPORT),
        ])
        db.commit()
    identity = {"id": 1}
    app = FastAPI(); app.include_router(router)
    def dependency():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[get_current_user_or_401] = lambda: identity["id"]
    with TestClient(app) as client:
        yield client, sessions, identity, engine, url, chart
    engine.dispose()


def test_report_uses_original_facts_and_frozen_chart(saved):
    client, _, _, _, _, chart = saved
    response = client.get('/conversations/1/report')
    assert response.status_code == 200
    report = response.json()
    assert report['source_message_id'] == 4
    assert report['question'] == '如何选择职业方向？'
    assert report['facts'] == {'topic': '如何选择职业方向？', 'currentSituation': '工作稳定'}
    assert report['profile']['bazi_chart'] == chart
    assert report['kind'] == 'topic'
    assert report['content'] == REPORT
    assert client.get('/conversations?type=bazi').json()['items'][0]['report_source_message_id'] == 4


def test_follow_up_and_another_full_reply_do_not_replace_initial_report(saved):
    client, sessions, *_ = saved
    with sessions() as db:
        db.add_all([
            Message(id=5, conversation_id=1, user_id=1, role='user', content='还应核对什么？'),
            Message(id=6, conversation_id=1, user_id=1, role='assistant', content=REPORT.replace('岗位职责', '合同条款')),
        ]); db.commit()
    assert client.get('/conversations/1/report').json()['content'] == REPORT


def test_reopens_from_new_database_engine_after_memory_is_discarded(saved):
    client, _, _, engine, url, _ = saved
    before = client.get('/conversations/1/report').json()
    engine.dispose()
    restarted_engine = create_engine(url, connect_args={"check_same_thread": False})
    restarted_sessions = sessionmaker(restarted_engine)
    def fresh_db():
        with restarted_sessions() as db:
            yield db
    client.app.dependency_overrides[get_db] = fresh_db
    assert client.get('/conversations/1/report').json() == before
    restarted_engine.dispose()


def test_foreign_user_and_deleted_report_are_not_accessible(saved):
    client, _, identity, *_ = saved
    identity['id'] = 2
    assert client.get('/conversations/1/report').status_code == 404
    identity['id'] = 1
    assert client.delete('/conversations/1').status_code == 204
    assert client.get('/conversations/1/report').status_code == 404


def test_no_complete_report_does_not_invent_one(saved):
    client, sessions, *_ = saved
    with sessions() as db:
        db.delete(db.get(Message, 4)); db.commit()
    assert client.get('/conversations/1/report').status_code == 409
    assert client.get('/conversations?type=bazi').json()['items'][0]['report_source_message_id'] is None


def test_headings_in_code_quotes_or_nested_lists_do_not_make_a_report():
    assert report_sections('```markdown\n' + REPORT + '\n```') == []
    assert report_sections('\n'.join('> ' + line for line in REPORT.splitlines())) == []
    assert report_sections('\n'.join('  ' + line for line in REPORT.splitlines())) == []
    assert report_sections('### 核心观察\n观察\n### 分析依据\n依据\n### 现实建议\n') == []
    with_questions = REPORT + '\n---SUGGESTED_QUESTIONS---\n应核对哪些条件？\n---END_SUGGESTED_QUESTIONS---'
    assert 'SUGGESTED' not in report_sections(with_questions)[-1]['body']
    assert len(report_sections('\n'.join(f'### {title}\n原始内容\n' for title in PERSONAL_TITLES))) == 7
    # Existing normalization adds a WORD JOINER to every heading.
    normalized = '\n'.join(f'### {title}\u2060\n完整原始内容\n' for title in PERSONAL_TITLES)
    assert [row['title'] for row in report_sections(normalized)] == PERSONAL_TITLES


@pytest.mark.parametrize('failure', [None, 'provider', 'save'])
def test_stream_commits_before_done_and_never_saves_failed_partial_reply(saved, monkeypatch, failure):
    import asyncio
    from app.chat import service
    from sqlalchemy import select, func
    _, sessions, *_ = saved
    appended = []
    monkeypatch.setattr(service, 'get_conv', lambda _: {'history': [], 'user_id': 1, 'db_conv_id': 1})
    monkeypatch.setattr(service, 'append_history', lambda *args: appended.append(args))
    monkeypatch.setattr(service.utils, 'load_system_prompt_from_db', lambda: 'configured prompt')
    monkeypatch.setattr(service.utils, 'build_full_system_prompt', lambda *_, **__: 'configured prompt')
    monkeypatch.setattr(service, 'should_stream', lambda _: True)
    monkeypatch.setattr('app.db.SessionLocal', sessions)
    def provider(*_, **kwargs):
        assert kwargs['require_complete'] is True
        yield REPORT
        if failure == 'provider':
            raise RuntimeError('disconnected before upstream DONE')
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    if failure == 'save':
        def cannot_save(*_, **__):
            raise RuntimeError('database unavailable')
        monkeypatch.setattr(service, '_save_db_exchange', cannot_save)
    with sessions() as db:
        response = service.send_chat('bazi_conv_1', '继续问', request=None, user_id=1, db=db)
    async def read():
        return b''.join([chunk async for chunk in response.body_iterator]).decode()
    body = asyncio.run(read())
    with sessions() as db:
        count = db.scalar(select(func.count()).select_from(Message))
    if failure:
        assert '"error"' in body and '[DONE]' not in body
        assert count == 4 and appended == []
    else:
        assert body.index('message_id') < body.index('[DONE]')
        assert count == 6 and len(appended) == 2


def test_exchange_rolls_back_both_messages_when_commit_fails(saved, monkeypatch):
    from app.chat.service import _save_db_exchange
    from sqlalchemy import select, func
    _, sessions, *_ = saved
    with sessions() as db:
        def fail_commit():
            raise RuntimeError('commit failed')
        monkeypatch.setattr(db, 'commit', fail_commit)
        with pytest.raises(RuntimeError):
            _save_db_exchange(db, 1, 1, '问题', REPORT)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 4


def test_stale_client_cannot_replace_original_report_facts(saved, monkeypatch):
    import asyncio
    from app.chat import service
    _, sessions, *_ = saved
    monkeypatch.setattr(service, 'get_conv', lambda _: {'history': [], 'user_id': 1, 'db_conv_id': 1})
    monkeypatch.setattr(service, 'append_history', lambda *_: None)
    monkeypatch.setattr(service.utils, 'load_system_prompt_from_db', lambda: 'test')
    monkeypatch.setattr(service.utils, 'build_full_system_prompt', lambda *_, **__: 'test')
    monkeypatch.setattr(service, 'should_stream', lambda _: True)
    captured = []
    monkeypatch.setattr(service, 'consultation_context', lambda db, context, history: captured.append(context) or [])
    def failed(*_, **__):
        raise RuntimeError('no reply')
        yield ''
    monkeypatch.setattr(service, 'call_deepseek_stream', failed)
    with sessions() as db:
        response = service.send_chat('bazi_conv_1', '追问', request=None, user_id=1, db=db,
            task_context={'taskType': 'career', 'facts': {'topic': '其他问题', 'currentSituation': '旧浏览器里的背景'}})
    async def read():
        return [chunk async for chunk in response.body_iterator]
    asyncio.run(read())
    assert captured[0]['facts']['topic'] == '如何选择职业方向？'
    with sessions() as db:
        assert db.get(Conversation, 1).task_context['facts']['currentSituation'] == '工作稳定'
