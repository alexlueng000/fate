"""First-generation ownership and transactions; isolated SQLite/model fixture."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.test.test_completed_reply import sessions, stats, ANSWER
from app.models.chat import Conversation, Message
from app.models.chat_turn_request import ChatTurnRequest
from app.models.liuyao_opening_request import LiuyaoOpeningRequest
from app.services.liuyao_opening_request import reserve_opening, opening_status, generate_opening
from app.services.chat_turn_request import mark_failed
from app.services.completed_reply import save_completed_exchange


@pytest.fixture
def openings(sessions):
    with sessions() as db:
        ChatTurnRequest.__table__.create(db.get_bind())
        LiuyaoOpeningRequest.__table__.create(db.get_bind())
    return sessions


def finish(db, reservation):
    return save_completed_exchange(db, reservation['conversation_id'], 1, '第一次解读', ANSWER,
                                  quota_type='liuyao_chat', turn_reservation=reservation)


def test_saved_opening_replays_at_zero_quota_with_its_original_context(openings):
    original = {'facts': {'topic': '原问题', 'currentSituation': '收到 offer'}}
    with openings() as db:
        first = reserve_opening(db, 1, 'test-hexagram', original)
        assert first['state'] == 'reserved'
        mid = finish(db, first['reservation'])
    with openings() as db:
        replay = reserve_opening(db, 1, 'test-hexagram', {'facts': {'topic': '改写问题'}})
        assert replay['state'] == 'succeeded' and replay['message_id'] == mid and replay['reply'] == ANSWER
        assert replay['task_context'] == original
        assert opening_status(db, 1, 'test-hexagram')['message_id'] == mid
    assert stats(openings, 'liuyao_chat') == (1, 2)


def test_two_tabs_create_one_opening_conversation_and_active_request(openings):
    def attempt(_):
        with openings() as db:
            return reserve_opening(db, 1, 'test-hexagram')['state']
    with ThreadPoolExecutor(max_workers=2) as pool:
        states = list(pool.map(attempt, range(2)))
    assert states.count('reserved') == 1 and states.count('pending') == 1
    with openings() as db:
        assert db.scalar(select(func.count()).select_from(LiuyaoOpeningRequest)) == 1
        assert db.scalar(select(func.count()).select_from(ChatTurnRequest)) == 1
        assert db.scalar(select(func.count()).select_from(Conversation)) == 3  # two fixture conversations + one opening
    assert stats(openings, 'liuyao_chat') == (0, 0)


@pytest.mark.parametrize('reason', ['failed', 'expired'])
def test_retry_reuses_context_and_conversation_rejecting_late_worker(openings, reason):
    with openings() as db:
        first = reserve_opening(db, 1, 'test-hexagram', {'facts': {'topic': '原问题'}})
        if reason == 'failed': mark_failed(db, first['reservation'])
        else:
            db.get(ChatTurnRequest, (1, first['request_key'])).lease_until = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        assert opening_status(db, 1, 'test-hexagram')['state'] == 'retryable'
        retry = reserve_opening(db, 1, 'test-hexagram', {'facts': {'topic': '另一问题'}})
        assert retry['conversation_id'] == first['conversation_id'] and retry['request_key'] == first['request_key']
        assert retry['task_context'] == first['task_context']
        assert retry['reservation']['token'] != first['reservation']['token']
        with pytest.raises(HTTPException): finish(db, first['reservation'])
        mark_failed(db, first['reservation'])
        assert opening_status(db, 1, 'test-hexagram')['state'] == 'pending'
        finish(db, retry['reservation'])
    assert stats(openings, 'liuyao_chat') == (1, 2)


def test_status_does_not_generate_and_cannot_read_another_user(openings):
    with openings() as db:
        assert opening_status(db, 1, 'test-hexagram')['state'] == 'idle'
        for operation in (opening_status, reserve_opening):
            with pytest.raises(HTTPException) as error: operation(db, 2, 'test-hexagram')
            assert error.value.status_code == 404
        assert db.scalar(select(func.count()).select_from(LiuyaoOpeningRequest)) == 0


def test_pre_migration_saved_report_is_returned_without_recreation(openings):
    with openings() as db:
        mid = save_completed_exchange(db, 2, 1, '旧第一次解读', ANSWER, quota_type='liuyao_chat')
        result = reserve_opening(db, 1, 'test-hexagram', {'facts': {'topic': '新背景'}})
        assert result == {'state': 'succeeded', 'conversation_id': 'liuyao_conv_2', 'message_id': mid, 'reply': ANSWER}
        assert db.scalar(select(func.count()).select_from(LiuyaoOpeningRequest)) == 0
    assert stats(openings, 'liuyao_chat') == (1, 2)


def test_opening_commit_failure_rolls_back_mapping_conversation_and_turn(openings, monkeypatch):
    with openings() as db:
        def fail(): raise RuntimeError('commit failed')
        monkeypatch.setattr(db, 'commit', fail)
        with pytest.raises(RuntimeError): reserve_opening(db, 1, 'test-hexagram')
    with openings() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 2
        assert db.scalar(select(func.count()).select_from(ChatTurnRequest)) == 0
        assert db.scalar(select(func.count()).select_from(LiuyaoOpeningRequest)) == 0


@pytest.mark.parametrize('failure', [False, True])
def test_actual_start_service_commits_or_releases_the_same_reserved_request(openings, monkeypatch, failure):
    from app.liuyao import chat_service as service
    monkeypatch.setattr('app.db.SessionLocal', openings)
    monkeypatch.setattr(service, 'retrieve_kb', lambda **_: [])
    monkeypatch.setattr(service.utils, 'load_liuyao_system_prompt_from_db', lambda: 'configured')
    monkeypatch.setattr(service, 'set_conv', lambda *_: None)
    monkeypatch.setattr(service, 'append_history', lambda *_: None)
    monkeypatch.setattr(service, 'consultation_context', lambda *_: [])
    monkeypatch.setattr(service, 'should_stream', lambda _: True)
    def provider(*_, **kwargs):
        assert kwargs['require_complete']
        if failure: raise RuntimeError('provider failed')
        yield ANSWER
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    async def read():
        with openings() as db:
            response = generate_opening(db, 1, 'test-hexagram', None, None)
            return b''.join([chunk async for chunk in response.body_iterator]).decode()
    body = asyncio.run(read())
    with openings() as db:
        assert opening_status(db, 1, 'test-hexagram')['state'] == ('retryable' if failure else 'succeeded')
        assert db.scalar(select(func.count()).select_from(Conversation)) == 3
    assert ('[DONE]' in body) == (not failure)
    assert stats(openings, 'liuyao_chat') == ((0, 0) if failure else (1, 2))


def test_http_duplicate_and_status_use_one_provider_and_fail_closed_without_table(openings, monkeypatch):
    from app.routers import liuyao
    from app.liuyao import chat_service
    from app.db import get_db_tx
    from app.deps import get_current_user
    calls = []
    def provider(*args, **kwargs):
        calls.append(1)
        db, reservation = args[3], kwargs['turn_reservation']
        finish(db, reservation)
        return f"liuyao_conv_{reservation['conversation_id']}", ANSWER
    monkeypatch.setattr(chat_service, 'start_liuyao_chat', provider)
    app = FastAPI(); app.include_router(liuyao.router)
    def dependency():
        with openings() as db: yield db
    app.dependency_overrides[get_db_tx] = dependency
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post('/liuyao/test-hexagram/chat/start', json={})
            assert response.status_code == 200, response.text
            assert response.json()['reply'] == ANSWER
        status = client.get('/liuyao/test-hexagram/chat/status')
        assert status.status_code == 200 and status.json()['state'] == 'succeeded'
        with openings() as db: LiuyaoOpeningRequest.__table__.drop(db.get_bind())
        assert client.post('/liuyao/test-hexagram/chat/start', json={}).status_code == 503
        assert client.get('/liuyao/test-hexagram/chat/status').status_code == 503
    assert len(calls) == 1 and stats(openings, 'liuyao_chat') == (1, 2)
