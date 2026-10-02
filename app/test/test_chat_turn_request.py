"""Durable ordinary-turn recovery with file transactions; no live model/MySQL."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.test.test_completed_reply import sessions, stats, ANSWER
from app.models.chat import Message
from app.models.chat_turn_request import ChatTurnRequest
from app.services.chat_turn_request import reserve_turn, request_status, mark_failed, run_turn
from app.services.completed_reply import save_completed_exchange

KEY = 'a' * 32
PAYLOAD = {'message': '应当先核对什么？'}


@pytest.fixture
def turns(sessions):
    with sessions() as db:
        ChatTurnRequest.__table__.create(db.get_bind())
    return sessions


def reserve(db, key=KEY, kind='bazi', cid='bazi_conv_1', payload=PAYLOAD):
    return reserve_turn(db, 1, cid, kind, key, payload)


def test_completed_request_replays_from_new_session_even_at_zero_quota(turns):
    with turns() as db:
        prepared = reserve(db)
        message_id = save_completed_exchange(db, 1, 1, PAYLOAD['message'], ANSWER, turn_reservation=prepared['reservation'])
    with turns() as db:
        replay = reserve(db)
        assert replay['state'] == 'succeeded' and replay['message_id'] == message_id and replay['reply'] == ANSWER
        assert request_status(db, 1, KEY) == replay
        assert db.get(ChatTurnRequest, (1, KEY)).active_conversation_id is None
    assert stats(turns) == (1, 2)


@pytest.mark.parametrize('change', ['payload', 'kind', 'cid', 'owner'])
def test_request_cannot_be_reused_for_another_question_or_account(turns, change):
    with turns() as db:
        reserve(db)
        if change == 'owner':
            with pytest.raises(HTTPException) as caught: request_status(db, 2, KEY)
            assert caught.value.status_code == 404
        else:
            with pytest.raises((HTTPException, ValueError)):
                reserve(db, payload={'message': '其他问题'} if change == 'payload' else PAYLOAD,
                        kind='liuyao' if change == 'kind' else 'bazi', cid='liuyao_conv_2' if change == 'cid' else 'bazi_conv_1')
    assert stats(turns) == (0, 0)


def test_same_request_pending_and_another_key_cannot_start_another_turn(turns):
    with turns() as db:
        reserve(db)
        assert reserve(db)['state'] == 'pending'
        with pytest.raises(HTTPException) as error: reserve(db, key='b' * 32)
        assert error.value.status_code == 409
    assert stats(turns) == (0, 0)


@pytest.mark.parametrize('reason', ['failure', 'expiry'])
def test_retry_uses_new_token_and_late_worker_cannot_save_or_charge(turns, reason):
    with turns() as db:
        first = reserve(db)['reservation']
        if reason == 'failure': mark_failed(db, first)
        else:
            db.get(ChatTurnRequest, (1, KEY)).lease_until = datetime.utcnow() - timedelta(seconds=1); db.commit()
        assert request_status(db, 1, KEY)['state'] == 'retryable'
        retry = reserve(db)['reservation']
        assert retry['token'] != first['token']
        with pytest.raises(HTTPException) as error:
            save_completed_exchange(db, 1, 1, PAYLOAD['message'], ANSWER, turn_reservation=first)
        assert error.value.status_code == 409
        mark_failed(db, first)
        assert request_status(db, 1, KEY)['state'] == 'pending'
        save_completed_exchange(db, 1, 1, PAYLOAD['message'], ANSWER, turn_reservation=retry)
    assert stats(turns) == (1, 2)


def test_changed_conversation_rejects_stale_answer(turns):
    with turns() as db:
        attempt = reserve(db)['reservation']
        db.add(Message(conversation_id=1, user_id=1, role='assistant', content='另一个已保存的回答')); db.commit()
        with pytest.raises(HTTPException) as error:
            save_completed_exchange(db, 1, 1, PAYLOAD['message'], ANSWER, turn_reservation=attempt)
        assert error.value.status_code == 409
    assert stats(turns) == (0, 1)


def test_commit_failure_rolls_back_answer_quota_and_success_status(turns, monkeypatch):
    with turns() as db:
        attempt = reserve(db)['reservation']
        def fail(): raise RuntimeError('commit unavailable')
        monkeypatch.setattr(db, 'commit', fail)
        with pytest.raises(RuntimeError):
            save_completed_exchange(db, 1, 1, PAYLOAD['message'], ANSWER, turn_reservation=attempt)
    with turns() as db: assert request_status(db, 1, KEY)['state'] == 'pending'
    assert stats(turns) == (0, 0)


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_reservations_have_one_active_slot(turns, same_key):
    def attempt(index):
        with turns() as db:
            try: return reserve(db, key=KEY if same_key or index == 0 else 'b' * 32)['state']
            except HTTPException as error:
                assert error.status_code == 409; return 'pending'
    with ThreadPoolExecutor(max_workers=2) as pool: states = list(pool.map(attempt, range(2)))
    assert states.count('reserved') == 1
    with turns() as db:
        assert len(db.scalars(select(ChatTurnRequest).where(ChatTurnRequest.active_conversation_id == 1)).all()) == 1


def test_cancelled_stream_releases_only_its_own_attempt(turns, monkeypatch):
    monkeypatch.setattr('app.db.SessionLocal', turns)
    def runner(_):
        async def stream():
            yield b'data: partial\n\n'
            await asyncio.sleep(0)
        return StreamingResponse(stream())
    async def consume():
        with turns() as db:
            response = run_turn(db, 1, 'bazi_conv_1', 'bazi', KEY, PAYLOAD, None, runner)
            await response.body_iterator.__anext__()
            await response.body_iterator.aclose()
    asyncio.run(consume())
    with turns() as db: assert request_status(db, 1, KEY)['state'] == 'retryable'
    assert stats(turns) == (0, 0)


@pytest.mark.parametrize('kind,endpoint', [('bazi', '/chat'), ('liuyao', '/liuyao/test-hexagram/chat'), ('liuyao', '/liuyao/test-hexagram/chat/quick')])
def test_http_duplicate_replays_saved_answer_without_second_provider_call(turns, monkeypatch, kind, endpoint):
    from app.routers import chat, liuyao
    from app.db import get_db, get_db_tx
    from app.deps import get_current_user, get_current_user_optional
    calls = []
    def provider(**kwargs):
        calls.append(kwargs)
        save_completed_exchange(kwargs['db'], 2 if kind == 'liuyao' else 1, 1, PAYLOAD['message'], ANSWER,
                                quota_type='liuyao_chat' if kind == 'liuyao' else 'chat', turn_reservation=kwargs['turn_reservation'])
        return ANSWER
    def bazi_provider(cid, message, request, **kwargs): return provider(**kwargs)
    monkeypatch.setattr(chat, 'send_chat', bazi_provider)
    monkeypatch.setattr(liuyao, 'send_liuyao_chat', provider)
    monkeypatch.setattr(liuyao, 'quick_liuyao_chat', provider)
    app = FastAPI(); app.include_router(chat.router); app.include_router(liuyao.router)
    def dependency():
        with turns() as db: yield db
    for dep in (get_db, get_db_tx): app.dependency_overrides[dep] = dependency
    for dep in (get_current_user, get_current_user_optional): app.dependency_overrides[dep] = lambda: SimpleNamespace(id=1)
    cid = 'liuyao_conv_2' if kind == 'liuyao' else 'bazi_conv_1'
    payload = {'conversation_id': cid, 'request_key': KEY, 'message': PAYLOAD['message']}
    if endpoint.endswith('quick'): payload = {'conversation_id': cid, 'request_key': KEY, 'label': '核对条件', 'prompt': PAYLOAD['message']}
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(endpoint, json=payload)
            assert response.status_code == 200, response.text
            assert response.json()['reply'] == ANSWER
        status = client.get(f'/chat/requests/{KEY}')
        assert status.status_code == 200 and status.json()['state'] == 'succeeded'
    assert len(calls) == 1 and stats(turns, 'liuyao_chat' if kind == 'liuyao' else 'chat') == (1, 2)


@pytest.mark.parametrize('kind,cid', [('bazi', 1), ('liuyao', 2)])
@pytest.mark.parametrize('failure', [False, True])
def test_stream_services_commit_attempt_with_answer_or_release_failed_attempt(turns, monkeypatch, kind, cid, failure):
    from app.chat import service as bazi
    from app.liuyao import chat_service as liuyao
    service = bazi if kind == 'bazi' else liuyao
    monkeypatch.setattr('app.db.SessionLocal', turns)
    monkeypatch.setattr(service, 'get_conv', lambda _: {'kind': kind, 'user_id': 1, 'db_conv_id': cid, 'history': [], 'pinned': 'configured prompt'})
    monkeypatch.setattr(service, 'append_history', lambda *_: None)
    monkeypatch.setattr(service, 'should_stream', lambda _: True)
    monkeypatch.setattr(service, 'consultation_context', lambda *_: [])
    monkeypatch.setattr(bazi.utils, 'load_system_prompt_from_db', lambda: 'configured prompt')
    monkeypatch.setattr(bazi.utils, 'build_full_system_prompt', lambda *_, **__: 'configured prompt')
    def provider(*_, **kwargs):
        assert kwargs['require_complete'] is True
        if failure: raise RuntimeError('provider failed')
        yield ANSWER
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    async def read():
        with turns() as db:
            def runner(reservation):
                method = bazi.send_chat if kind == 'bazi' else liuyao.send_liuyao_chat
                return method(f'{kind}_conv_{cid}', PAYLOAD['message'], None, user_id=1, db=db, turn_reservation=reservation)
            response = run_turn(db, 1, f'{kind}_conv_{cid}', kind, KEY, PAYLOAD, None, runner)
            return b''.join([chunk async for chunk in response.body_iterator]).decode()
    body = asyncio.run(read())
    with turns() as db:
        assert request_status(db, 1, KEY)['state'] == ('retryable' if failure else 'succeeded')
    assert ('[DONE]' in body) == (not failure)
    assert stats(turns, 'chat' if kind == 'bazi' else 'liuyao_chat') == ((0, 0) if failure else (1, 2))
