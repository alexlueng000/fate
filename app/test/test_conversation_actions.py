"""Durable action contracts using SQLite and a deterministic model fixture."""
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import get_db, get_db_tx
from app.deps import get_current_user_optional, get_current_user
from app.models.chat import Conversation, Message
from app.models.profile import UserProfile
from app.models.liuyao import LiuyaoHexagram
from app.models.quota import UserQuota
from app.models.message_rating import MessageRating
from app.chat.consultation import bounded_history
from app.services.conversation_report import first_report, PERSONAL_TITLES
from app.services.conversation_actions import append_regeneration, saved_messages

REPORT = '### 核心观察\n原观察。\n### 分析依据\n原依据。\n### 现实建议\n原建议。'
NEW_REPORT = REPORT.replace('原', '新')
CHART = {'gender': '男', 'four_pillars': {'year': ['甲', '子'], 'day': ['戊', '辰']}, 'dayun': []}
FACTS = {'taskType': 'career', 'facts': {'topic': '是否换工作？', 'currentSituation': '收到 offer'}}


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'actions.sqlite'}", connect_args={'check_same_thread': False})
    for model in (UserProfile, LiuyaoHexagram, Conversation, Message, UserQuota, MessageRating):
        model.__table__.create(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(UserProfile(id=1, user_id=1, gender='male', birth_date=date(1993, 3, 9), birth_time=time(7), birth_location='上海', bazi_chart={'mingpan': CHART}))
        db.add(LiuyaoHexagram(id=1, user_id=1, hexagram_id='saved-hex', question='是否换工作？', method='number', timestamp=datetime(2026, 10, 3), main_gua='乾', change_gua='姤'))
        db.add_all([Conversation(id=1, user_id=1, profile_id=1, title='八字', bazi_chart_snapshot=CHART, task_context=FACTS),
                    Conversation(id=2, user_id=1, liuyao_hexagram_id=1, title='六爻', task_context=FACTS)])
        db.add_all([Message(id=cid * 2 - 1, conversation_id=cid, user_id=1, role='user', content='是否换工作？') for cid in (1, 2)])
        db.add_all([Message(id=cid * 2, conversation_id=cid, user_id=1, role='assistant', content=REPORT) for cid in (1, 2)])
        db.add(MessageRating(message_id=2, user_id=1, rating_type='up'))
        db.add_all([UserQuota(user_id=1, quota_type=kind, total_quota=1, used_quota=1) for kind in ('chat', 'liuyao_chat')])
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def provider(monkeypatch, sessions):
    from app.chat import service as bazi
    from app.liuyao import chat_service as liuyao
    monkeypatch.setattr('app.db.SessionLocal', sessions)
    for service in (bazi, liuyao):
        monkeypatch.setattr(service, 'get_conv', lambda _: None)
        monkeypatch.setattr(service, 'retrieve_kb', lambda *_, **__: [])
        monkeypatch.setattr(service, 'consultation_context', lambda db, facts, history: [{'role': 'user', 'content': facts['facts']['currentSituation']}] if facts else [])
    monkeypatch.setattr(bazi.utils, 'load_system_prompt_from_db', lambda: 'configured bazi')
    monkeypatch.setattr(bazi.utils, 'load_report_system_prompt_from_db', lambda: 'configured personal report')
    monkeypatch.setattr(bazi.utils, 'build_full_system_prompt', lambda *_, **__: 'configured bazi')
    monkeypatch.setattr(liuyao.utils, 'load_liuyao_system_prompt_from_db', lambda: 'configured liuyao')
    monkeypatch.setattr(liuyao, 'build_system_prompt', lambda hexagram, *_, **__: f'原卦：{hexagram.hexagram_id}')
    monkeypatch.setattr('app.chat.store.delete_conv', lambda _: True)
    monkeypatch.setattr(bazi, 'delete_conv', lambda _: True)
    calls = []
    def model(messages, **kwargs):
        assert kwargs['require_complete'] is True
        calls.append(messages)
        return NEW_REPORT
    monkeypatch.setattr(bazi, 'call_deepseek', model)
    monkeypatch.setattr(liuyao, 'call_deepseek', model)
    return bazi, liuyao, calls


@pytest.mark.parametrize('kind,cid,target', [('bazi', 1, 2), ('liuyao', 2, 4)])
def test_regeneration_recovers_database_and_keeps_original_report_rating_and_quota(sessions, provider, kind, cid, target):
    bazi, liuyao, calls = provider
    with sessions() as db:
        result = (bazi.regenerate if kind == 'bazi' else liuyao.regenerate_liuyao_chat)(f'{kind}_conv_{cid}', user_id=1, db=db, expected_message_id=target)
    with sessions() as db:
        rows = saved_messages(db, cid)
        assert [row.role for row in rows] == ['user', 'assistant', 'assistant']
        assert rows[1].content == REPORT and rows[2].id == result['message_id']
        assert '新建议' in rows[2].content and first_report(rows)[0].id == target
        assert db.scalar(select(MessageRating)).message_id == 2
        assert all(quota.used_quota == 1 for quota in db.scalars(select(UserQuota)))
    assert '收到 offer' in str(calls[0]) and REPORT not in str(calls[0])
    if kind == 'liuyao':
        assert 'saved-hex' in calls[0][0]['content']
    else:
        assert '年柱 甲子' in calls[0][0]['content']


@pytest.mark.parametrize('kind,cid,target', [('bazi', 1, 2), ('liuyao', 2, 4)])
@pytest.mark.parametrize('failure', ['provider', 'empty', 'commit', 'stale', 'owner'])
def test_failed_regeneration_preserves_saved_answers(sessions, provider, monkeypatch, kind, cid, target, failure):
    bazi, liuyao, calls = provider
    service = bazi if kind == 'bazi' else liuyao
    if failure in ('provider', 'empty'):
        def model(*_, **__):
            if failure == 'provider': raise RuntimeError('provider disconnected')
            return ''
        monkeypatch.setattr(service, 'call_deepseek', model)
    with sessions() as db:
        if failure == 'commit':
            def fail_commit(): raise RuntimeError('database unavailable')
            monkeypatch.setattr(db, 'commit', fail_commit)
        with pytest.raises((RuntimeError, ValueError, HTTPException)) as error:
            (bazi.regenerate if kind == 'bazi' else liuyao.regenerate_liuyao_chat)(f'{kind}_conv_{cid}', user_id=2 if failure == 'owner' else 1, db=db, expected_message_id=999 if failure == 'stale' else target)
        if failure == 'stale':
            assert error.value.status_code == 409 and calls == []
    with sessions() as db:
        assert [row.content for row in saved_messages(db, cid)] == ['是否换工作？', REPORT]
        assert all(quota.used_quota == 1 for quota in db.scalars(select(UserQuota)))


def test_answer_becoming_stale_during_model_call_cannot_append(sessions, provider, monkeypatch):
    bazi, _, _ = provider
    def competing_model(*_, **__):
        with sessions() as other:
            append_regeneration(other, 1, 1, 2, '另一个已保存的完整回答。', 'bazi')
        return NEW_REPORT
    monkeypatch.setattr(bazi, 'call_deepseek', competing_model)
    with sessions() as db:
        with pytest.raises(HTTPException) as error:
            bazi.regenerate('bazi_conv_1', user_id=1, db=db, expected_message_id=2)
        assert error.value.status_code == 409
    with sessions() as db:
        assert [row.content for row in saved_messages(db, 1)] == ['是否换工作？', REPORT, '另一个已保存的完整回答。']


def test_incomplete_personal_regeneration_cannot_replace_or_append(sessions, provider):
    bazi, _, _ = provider
    original = '\n'.join(f'### {title}\n完整原报告。' for title in PERSONAL_TITLES)
    with sessions() as db:
        db.get(Message, 1).content = '我的命盘信息如下：请生成完整报告。'
        db.get(Message, 2).content = original
        db.get(UserProfile, 1).ai_report = original
        db.commit()
        with pytest.raises(ValueError, match='章节未完整生成'):
            bazi.regenerate('bazi_conv_1', user_id=1, db=db)
    with sessions() as db:
        assert db.get(UserProfile, 1).ai_report == original
        assert len(saved_messages(db, 1)) == 2


@pytest.mark.parametrize('identity', [1, 2, None])
def test_clear_http_forks_only_owned_bazi_and_keeps_archive(sessions, provider, monkeypatch, identity):
    bazi, _, _ = provider
    from app.routers.chat import router
    monkeypatch.setattr(bazi, 'get_conv', lambda _: {'user_id': 1, 'history': []})
    app = FastAPI(); app.include_router(router)
    def dependency():
        with sessions() as db: yield db
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(id=identity) if identity else None
    with TestClient(app) as client:
        response = client.post('/chat/clear', json={'conversation_id': 'bazi_conv_1'})
    with sessions() as db:
        assert first_report(saved_messages(db, 1))[0].content == REPORT
        assert db.get(MessageRating, 1).rating_type == 'up'
        if identity == 1:
            assert response.status_code == 200 and response.json()['ok']
            cid = response.json()['conversation_id']; assert cid != 'bazi_conv_1'
            new = db.get(Conversation, int(cid.removeprefix('bazi_conv_')))
            assert new.user_id == 1 and new.profile_id == 1 and new.bazi_chart_snapshot == CHART
            assert new.task_context is None and saved_messages(db, new.id) == []
        else:
            assert response.status_code == 404
            assert len(db.scalars(select(Conversation)).all()) == 2


def test_clear_new_session_uses_frozen_chart_without_old_history_after_cache_loss(sessions, provider, monkeypatch):
    bazi, _, calls = provider
    cache = {}
    monkeypatch.setattr(bazi, 'get_conv', cache.get)
    monkeypatch.setattr(bazi, 'set_conv', lambda cid, data: cache.update({cid: data}))
    monkeypatch.setattr(bazi, 'append_history', lambda *args: None)
    monkeypatch.setattr(bazi, 'should_stream', lambda _: False)
    with sessions() as db:
        # Saved guest-to-account conversations may have a chart without a profile.
        db.get(Conversation, 1).profile_id = None
        db.scalar(select(UserQuota).where(UserQuota.quota_type == 'chat')).used_quota = 0
        db.commit()
        cid = bazi.clear('bazi_conv_1', user_id=1, db=db)['conversation_id']
    with sessions() as db:
        bazi.send_chat(cid, '这个空白会话的新问题', request=None, user_id=1, db=db)
    assert '年柱 甲子' in calls[0][0]['content']
    assert '是否换工作' not in str(calls[0]) and '收到 offer' not in str(calls[0])
    with sessions() as db:
        assert first_report(saved_messages(db, 1))[0].content == REPORT


def test_model_history_uses_latest_alternative_but_keeps_original_question():
    history = [{'role': 'user', 'content': '原问题'}, {'role': 'assistant', 'content': '原回答'},
               {'role': 'assistant', 'content': '新回答'}, {'role': 'user', 'content': '接着问'}]
    assert [row['content'] for row in bounded_history(history, 2)] == ['原问题', '新回答', '接着问']
    assert [row['content'] for row in history] == ['原问题', '原回答', '新回答', '接着问']


@pytest.mark.parametrize('kind,cid,target', [('bazi', 1, 2), ('liuyao', 2, 4)])
def test_regeneration_http_failure_is_actionable_and_keeps_original(sessions, provider, monkeypatch, kind, cid, target):
    bazi, liuyao, _ = provider
    from app.routers.chat import router as bazi_router
    from app.routers.liuyao import router as liuyao_router
    def unavailable(*_, **__): raise RuntimeError('internal provider connection details')
    monkeypatch.setattr(bazi if kind == 'bazi' else liuyao, 'call_deepseek', unavailable)
    app = FastAPI(); app.include_router(bazi_router); app.include_router(liuyao_router)
    def dependency():
        with sessions() as db: yield db
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        response = client.post('/chat/regenerate' if kind == 'bazi' else '/liuyao/saved-hex/chat/regenerate',
                               json={'conversation_id': f'{kind}_conv_{cid}', 'expected_message_id': target})
    assert response.status_code == 503 and '原回答已保留' in response.json()['detail']
    assert 'internal provider' not in response.text
    with sessions() as db:
        assert len(saved_messages(db, cid)) == 2 and first_report(saved_messages(db, cid))[0].content == REPORT


def test_clear_transaction_failure_and_wrong_kind_cannot_change_archive(sessions, provider, monkeypatch):
    bazi, _, _ = provider
    with sessions() as db:
        with pytest.raises(ValueError, match='会话不存在'):
            bazi.clear('bazi_conv_2', user_id=1, db=db)
        def fail_commit(): raise RuntimeError('database unavailable')
        monkeypatch.setattr(db, 'commit', fail_commit)
        with pytest.raises(RuntimeError): bazi.clear('bazi_conv_1', user_id=1, db=db)
    with sessions() as db:
        assert len(db.scalars(select(Conversation)).all()) == 2
        assert first_report(saved_messages(db, 1))[0].content == REPORT


def test_regeneration_cannot_use_another_hexagram_for_same_account(sessions, provider):
    _, liuyao, calls = provider
    with sessions() as db:
        with pytest.raises(ValueError, match='会话不存在'):
            liuyao.regenerate_liuyao_chat('liuyao_conv_2', user_id=1, db=db, expected_hexagram_id=999)
    assert calls == []
