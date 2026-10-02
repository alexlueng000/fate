"""Real file transactions with a deterministic provider; no live model/MySQL."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models.chat import Conversation, Message
from app.models.profile import UserProfile
from app.models.quota import UserQuota
from app.models.liuyao import LiuyaoHexagram
from app.services.completed_reply import save_completed_exchange
from app.routers.profile import _report_source
from app.services.conversation_report import PERSONAL_TITLES

ANSWER = '### 核心观察\n\n先核对条件。\n\n### 分析依据\n\n明确的背景仅为收到 offer。\n\n### 现实建议\n\n核实职责后再选择。'
PERSONAL_ANSWER = '\n\n'.join(f'### {title}\n\n该章节的完整测试内容。' for title in PERSONAL_TITLES)
CHART = {'gender': '男', 'four_pillars': {'year': ['甲', '子'], 'month': ['丙', '寅'], 'day': ['戊', '辰'], 'hour': ['庚', '午']}, 'dayun': [{'age': 8, 'start_year': 2000, 'pillar': ['丁', '卯']}], 'solar_date': '1993-03-09 07:00:00'}


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'complete.sqlite'}", connect_args={'check_same_thread': False, 'timeout': 10})
    for model in (UserProfile, LiuyaoHexagram, Conversation, Message, UserQuota):
        model.__table__.create(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(UserProfile(id=1, user_id=1, gender='male', birth_date=date(1993, 3, 9), birth_time=time(7), birth_location='上海', bazi_chart={'mingpan': CHART}))
        db.add(LiuyaoHexagram(id=1, user_id=1, hexagram_id='test-hexagram', question='是否接受 offer？', method='number', timestamp=datetime(2026, 10, 2), main_gua='乾', change_gua='姤'))
        db.add_all([Conversation(id=1, user_id=1, profile_id=1, title='八字', bazi_chart_snapshot=CHART), Conversation(id=2, user_id=1, liuyao_hexagram_id=1, title='六爻')])
        db.add_all([UserQuota(user_id=1, quota_type=kind, total_quota=1, used_quota=0) for kind in ('chat', 'liuyao_chat')])
        db.commit()
    yield factory
    engine.dispose()


def stats(sessions, kind='chat'):
    with sessions() as db:
        return db.scalar(select(UserQuota.used_quota).where(UserQuota.quota_type == kind)), db.scalar(select(func.count()).select_from(Message))


@pytest.mark.parametrize('kind,cid', [('chat', 1), ('liuyao_chat', 2)])
def test_success_records_pair_and_one_use_together(sessions, kind, cid):
    with sessions() as db:
        message_id = save_completed_exchange(db, cid, 1, '问题', ANSWER, quota_type=kind)
        assert db.get(Message, message_id).role == 'assistant'
    assert stats(sessions, kind) == (1, 2)


@pytest.mark.parametrize('failure', ['commit', 'empty', 'owner', 'type', 'quota'])
def test_failure_rolls_back_messages_and_quota(sessions, monkeypatch, failure):
    if failure == 'quota':
        with sessions() as db:
            db.scalar(select(UserQuota).where(UserQuota.quota_type == 'chat')).used_quota = 1; db.commit()
    with sessions() as db:
        if failure == 'commit':
            def fail(): raise RuntimeError('commit failed')
            monkeypatch.setattr(db, 'commit', fail)
        with pytest.raises((RuntimeError, ValueError, HTTPException)):
            save_completed_exchange(db, 1, 2 if failure == 'owner' else 1, '问题', '' if failure == 'empty' else ANSWER,
                                    quota_type='liuyao_chat' if failure == 'type' else 'chat')
    assert stats(sessions) == (1 if failure == 'quota' else 0, 0)


def test_last_use_cannot_be_consumed_twice_by_concurrent_completions(sessions):
    def finish(_):
        with sessions() as db:
            try:
                return save_completed_exchange(db, 1, 1, '并发问题', ANSWER)
            except HTTPException as error:
                assert error.status_code == 429
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(finish, range(2)))
    assert sum(value is not None for value in outcomes) == 1
    assert stats(sessions) == (1, 2)


def test_period_reset_is_part_of_transaction_and_unlimited_still_counts(sessions):
    with sessions() as db:
        quota = db.scalar(select(UserQuota).where(UserQuota.quota_type == 'chat'))
        quota.period = 'daily'; quota.used_quota = 1; quota.last_reset_at = datetime.utcnow() - timedelta(days=2); db.commit()
        save_completed_exchange(db, 1, 1, '问题', ANSWER)
    assert stats(sessions) == (1, 2)
    with sessions() as db:
        quota = db.scalar(select(UserQuota).where(UserQuota.quota_type == 'chat')); quota.total_quota = -1; db.commit()
        save_completed_exchange(db, 1, 1, '下一问', ANSWER)
    assert stats(sessions) == (2, 4)


@pytest.mark.parametrize('changed', [False, True])
def test_personal_report_and_server_source_survive_a_new_session(sessions, changed):
    with sessions() as db:
        if changed:
            db.get(UserProfile, 1).bazi_chart = {'mingpan': {**CHART, 'gender': '女'}}; db.commit()
        message_id = save_completed_exchange(db, 1, 1, '报告', PERSONAL_ANSWER, save_profile_report=True)
    with sessions() as db:
        profile = db.get(UserProfile, 1)
        assert profile.ai_report == (None if changed else PERSONAL_ANSWER)
        source = _report_source(db, profile)
        assert source is None if changed else source.conversation_id == 1
        assert db.get(Message, message_id).content == PERSONAL_ANSWER


@pytest.mark.parametrize('entry', ['start', 'send'])
@pytest.mark.parametrize('failure', [None, 'provider', 'truncated', 'save', 'cache'])
def test_liuyao_stream_done_requires_saved_complete_reply(sessions, monkeypatch, entry, failure):
    from app.liuyao import chat_service as service
    from app.chat.deepseek_client import DeepSeekEmptyResponseError
    monkeypatch.setattr('app.db.SessionLocal', sessions)
    monkeypatch.setattr(service, 'retrieve_kb', lambda *_, **__: [])
    monkeypatch.setattr(service.utils, 'load_liuyao_system_prompt_from_db', lambda: 'test prompt')
    monkeypatch.setattr(service, 'build_system_prompt', lambda *_, **__: 'test prompt')
    monkeypatch.setattr(service, 'build_opening_user_message', lambda _: '是否接受 offer？')
    monkeypatch.setattr(service, 'consultation_context', lambda *_, **__: [])
    monkeypatch.setattr(service, 'should_stream', lambda _: True)
    monkeypatch.setattr(service, 'get_conv', lambda _: {'kind': 'liuyao', 'user_id': 1, 'db_conv_id': 2, 'history': [], 'pinned': 'test prompt'})
    monkeypatch.setattr(service, 'set_conv', lambda *_, **__: None)
    appended = []
    def append(*args):
        if failure == 'cache': raise RuntimeError('cache unavailable')
        appended.append(args)
    monkeypatch.setattr(service, 'append_history', append)
    monkeypatch.setattr('app.chat.store.delete_conv', lambda *_: True)
    def provider(*_, **kwargs):
        assert kwargs['require_complete'] is True
        if failure == 'provider': raise RuntimeError('provider failed')
        yield ANSWER
        if failure == 'truncated': raise DeepSeekEmptyResponseError('missing stop')
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    if failure == 'save':
        def cannot_save(*_, **__): raise RuntimeError('save failed')
        monkeypatch.setattr(service, 'save_completed_exchange', cannot_save)
    with sessions() as db:
        if entry == 'start':
            response = service.start_liuyao_chat(db.get(LiuyaoHexagram, 1), request=None, user_id=1, db=db)
        else:
            response = service.send_liuyao_chat('liuyao_conv_2', '继续问', request=None, user_id=1, db=db)
    async def read():
        return b''.join([chunk async for chunk in response.body_iterator]).decode()
    body = asyncio.run(read())
    if failure in ('provider', 'truncated', 'save'):
        assert '"error"' in body and '[DONE]' not in body
        assert stats(sessions, 'liuyao_chat') == (0, 0) and appended == []
    else:
        assert body.index('message_id') < body.index('[DONE]')
        assert stats(sessions, 'liuyao_chat') == (1, 2)


def test_redis_cache_round_trip_preserves_facts_and_hexagram_identifier():
    from app.chat.store import _serialize, _deserialize
    original = {'task_context': {'taskType': 'career', 'facts': {'topic': '选择工作？'}}, 'history': [], 'liuyao_hexagram_id': 3}
    assert _deserialize(_serialize(original)) == original
    assert _deserialize({'task_context': "{'legacy': 'unparseable'}"})['task_context'] is None


@pytest.mark.parametrize('failure', [None, 'incomplete', 'provider', 'save', 'cache', 'quota'])
def test_personal_stream_requires_all_chapters_and_atomic_save(sessions, monkeypatch, failure):
    from app.chat import service
    monkeypatch.setattr('app.db.SessionLocal', sessions)
    monkeypatch.setattr(service.utils, 'load_report_system_prompt_from_db', lambda: 'configured report prompt')
    monkeypatch.setattr(service.utils, 'build_full_system_prompt', lambda *_, **__: 'configured report prompt')
    monkeypatch.setattr(service, 'should_stream', lambda _: True)
    monkeypatch.setattr(service, 'set_conv', lambda *_, **__: None)
    monkeypatch.setattr('app.chat.store.delete_conv', lambda *_: True)
    def cache(*_):
        if failure == 'cache': raise RuntimeError('cache unavailable')
    monkeypatch.setattr(service, 'append_history', cache)
    def provider(messages, **kwargs):
        assert kwargs['require_complete'] is True
        assert all(f'### {title}' in messages[-1]['content'] for title in PERSONAL_TITLES)
        yield ANSWER if failure == 'incomplete' else PERSONAL_ANSWER
        if failure == 'provider': raise RuntimeError('provider disconnected')
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    if failure == 'save':
        def cannot_save(*_, **__): raise RuntimeError('save failed')
        monkeypatch.setattr(service, '_save_db_exchange', cannot_save)
    with sessions() as db:
        response = service.start_chat(CHART, None, 0, None, user_id=1, db=db, profile_id=1)
    if failure == 'quota':
        with sessions() as db:
            db.scalar(select(UserQuota).where(UserQuota.quota_type == 'chat')).used_quota = 1
            db.commit()
    async def read():
        return b''.join([chunk async for chunk in response.body_iterator]).decode()
    body = asyncio.run(read())
    with sessions() as db:
        report = db.get(UserProfile, 1).ai_report
        source = _report_source(db, db.get(UserProfile, 1))
    if failure in ('incomplete', 'provider', 'save', 'quota'):
        assert '[DONE]' not in body and '"error"' in body
        assert report is None and source is None
        assert stats(sessions) == (1 if failure == 'quota' else 0, 0)
    else:
        delivered = [json.loads(line[6:])['text'] for line in body.splitlines()
                     if line.startswith('data: {') and '"text"' in line]
        assert report == delivered[-1] and source.conversation_id == 3
        assert body.index('message_id') < body.index('[DONE]')
        assert stats(sessions) == (1, 2)


@pytest.mark.parametrize('kind,cid', [('chat', 1), ('liuyao_chat', 2)])
def test_follow_up_uses_saved_history_and_facts_even_when_worker_cache_is_stale(sessions, monkeypatch, kind, cid):
    from app.chat import service as bazi
    from app.liuyao import chat_service as liuyao
    service = bazi if kind == 'chat' else liuyao
    original = {'taskType': 'career', 'facts': {'topic': '真实原问题', 'currentSituation': '真实背景'}}
    with sessions() as db:
        db.get(Conversation, cid).task_context = original
        db.add_all([Message(conversation_id=cid, user_id=1, role='user', content='服务端保存的原问题'),
                    Message(conversation_id=cid, user_id=1, role='assistant', content='服务端保存的分析')])
        db.commit()
    monkeypatch.setattr('app.db.SessionLocal', sessions)
    monkeypatch.setattr(service, 'get_conv', lambda _: {'kind': 'bazi' if kind == 'chat' else 'liuyao', 'user_id': 1, 'db_conv_id': cid,
                                                     'history': [{'role': 'user', 'content': '过期缓存中的错误问题'}], 'task_context': {'facts': {'topic': '过期问题'}}})
    monkeypatch.setattr(service, 'append_history', lambda *_: None)
    monkeypatch.setattr(service, 'should_stream', lambda _: True)
    seen = []
    def context(db, facts, history):
        assert facts == original
        return []
    monkeypatch.setattr(service, 'consultation_context', context)
    monkeypatch.setattr(bazi.utils, 'load_system_prompt_from_db', lambda: 'configured prompt')
    monkeypatch.setattr(bazi.utils, 'build_full_system_prompt', lambda *_, **__: 'configured prompt')
    def provider(messages, **_):
        seen.extend(messages)
        yield ANSWER
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    with sessions() as db:
        response = (bazi.send_chat(f'bazi_conv_{cid}', '下一问', None, user_id=1, db=db) if kind == 'chat'
                    else liuyao.send_liuyao_chat(f'liuyao_conv_{cid}', '下一问', None, user_id=1, db=db))
    async def read():
        return b''.join([chunk async for chunk in response.body_iterator]).decode()
    assert '[DONE]' in asyncio.run(read())
    contents = [row['content'] for row in seen]
    assert '服务端保存的原问题' in contents and '服务端保存的分析' in contents
    assert '过期缓存中的错误问题' not in contents
    assert stats(sessions, kind) == (1, 4)


def test_stale_period_check_does_not_erase_a_completed_use(sessions):
    from app.services.quota import QuotaService
    with sessions() as db:
        quota = db.scalar(select(UserQuota).where(UserQuota.quota_type == 'chat'))
        quota.period = 'daily'; quota.used_quota = 1
        quota.last_reset_at = datetime.utcnow() - timedelta(days=2)
        db.commit()
    with sessions() as stale_db:
        stale = stale_db.scalar(select(UserQuota).where(UserQuota.quota_type == 'chat'))
        with sessions() as fresh_db:
            assert QuotaService.check_available(fresh_db, 1, 'chat')[0] is True
            save_completed_exchange(fresh_db, 1, 1, '已完成问题', ANSWER)
        QuotaService.reset_quota_if_needed(stale_db, stale)
    assert stats(sessions) == (1, 2)
    with sessions() as db:
        assert QuotaService.check_available(db, 1, 'chat')[0] is False
