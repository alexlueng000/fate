"""Owned read recovery, precise reply provenance and no-charge stale completion."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func, text
from app.models.chat import Conversation, Message
from app.models.consultation import ConsultationPass, ConsultationRequest
from app.services import consultation_passes as service
from app.deps import get_current_user
from app.routers import consultations
from app.test.test_consultation_api import client  # noqa: F401

BODY = {'pass_id': 1, 'request_key': 'recover-key-1', 'message': '需要核实哪些条件？'}


def reserve(sessions, age=0):
    with sessions() as db:
        item = service.reserve(db, 1, 1, 1, BODY['request_key'], BODY['message'], datetime.utcnow() - timedelta(minutes=age))
        db.commit()
        return item.id


def test_saved_reply_has_exact_message_pointer_and_exhausted_replay(client, monkeypatch):
    http, sessions, _ = client
    calls = []
    def model(*_, **__):
        calls.append(1)
        yield '完整建议：先核实职责。'
    monkeypatch.setattr('app.chat.deepseek_client.call_deepseek_stream', model)
    with sessions() as db:
        db.get(ConsultationPass, 1).reply_limit = 1
        db.commit()
    response = http.post('/consultations/1/messages', json=BODY)
    assert '[DONE]' in response.text
    saved = http.get('/consultations/1/requests/recover-key-1').json()
    assert saved['status'] == 'SUCCEEDED' and saved['message'] == BODY['message']
    assert saved['baseline_message_id'] == 0
    assert f'"message_id": {saved["message_id"]}' in response.text
    with sessions() as db:
        message = db.get(Message, saved['message_id'])
        assert (message.user_id, message.conversation_id, message.role, message.content) == (1, 1, 'assistant', saved['reply'])
        assert db.get(ConsultationPass, 1).replies_used == 1
    assert '[DONE]' in http.post('/consultations/1/messages', json=BODY).text
    assert calls == [1]
    assert http.get('/consultations/1/request').json() == {'status': 'IDLE', 'conversation_id': 1}


@pytest.mark.parametrize('age,expected', [(0, 'PENDING'), (16, 'EXPIRED')])
def test_pending_discovery_restores_original_and_never_writes(client, age, expected):
    http, sessions, _ = client
    request_id = reserve(sessions, age)
    for path in ('request', 'requests/recover-key-1'):
        result = http.get(f'/consultations/1/{path}')
        assert result.status_code == 200
        data = result.json()
        assert (data['status'], data['message'], data['pass_id'], data['request_key']) == (expected, BODY['message'], 1, BODY['request_key'])
        assert data['reply'] is None and data['message_id'] is None
    with sessions() as db:
        assert db.get(ConsultationRequest, request_id).status == 'PENDING'
        assert db.get(ConsultationPass, 1).replies_used == 0
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_failed_discovery_only_returns_current_conversation_attempt(client):
    http, sessions, _ = client
    request_id = reserve(sessions)
    with sessions() as db:
        assert not service.finish(db, request_id)
        db.commit()
    assert http.get('/consultations/1/request').json()['status'] == 'FAILED'
    with sessions() as db:
        db.add(Message(user_id=1, conversation_id=1, role='assistant', content='随后已保存的普通回复'))
        db.commit()
    assert http.get('/consultations/1/request').json()['status'] == 'IDLE'
    assert http.get('/consultations/1/requests/recover-key-1').json()['status'] == 'FAILED'


@pytest.mark.parametrize('path', ['request', 'requests/recover-key-1'])
def test_recovery_never_exposes_foreign_or_disabled_requests(client, monkeypatch, path):
    http, sessions, app = client
    reserve(sessions)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2)
    assert http.get(f'/consultations/1/{path}').status_code == 404
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    monkeypatch.setattr(consultations.settings, 'consultation_enabled', False)
    assert http.get(f'/consultations/1/{path}').status_code == 404


@pytest.mark.parametrize('damage', ['body', 'reply', 'pointer', 'owner', 'role', 'conversation'])
def test_corrupt_provenance_is_rejected_for_read_and_replay(client, damage):
    http, sessions, _ = client
    assert '[DONE]' in http.post('/consultations/1/messages', json=BODY).text
    with sessions() as db:
        item = db.scalar(select(ConsultationRequest))
        message = db.get(Message, item.message_id)
        if damage == 'body': item.user_message = '另一条原问题'
        if damage == 'reply': item.reply = '不是已保存的回复'
        if damage == 'pointer': item.message_id = 999999
        if damage == 'owner': message.user_id = 2
        if damage == 'role': message.role = 'user'
        if damage == 'conversation':
            db.add(Conversation(id=2, user_id=1, title='另一个问题'))
            message.conversation_id = 2
        db.commit()
    assert http.get('/consultations/1/requests/recover-key-1').status_code == 409
    assert http.post('/consultations/1/messages', json=BODY).status_code == 409
    with sessions() as db:
        assert db.get(ConsultationPass, 1).replies_used == 1


@pytest.mark.parametrize('damage', ['new_message', 'missing_baseline', 'changed_body'])
def test_stale_or_unverifiable_completion_is_failed_without_charge(client, damage):
    _, sessions, _ = client
    request_id = reserve(sessions)
    with sessions() as db:
        item = db.get(ConsultationRequest, request_id)
        if damage == 'new_message':
            db.add(Message(user_id=1, conversation_id=1, role='assistant', content='会话已更新'))
        elif damage == 'missing_baseline': item.baseline_message_id = None
        else: item.user_message = '损坏的问题'
        db.commit()
        assert not service.finish(db, request_id, '过期上下文的回答')
        db.commit()
        assert item.status == 'FAILED' and item.message_id is None
        assert db.get(ConsultationPass, 1).replies_used == 0
        assert db.scalar(select(func.count()).select_from(Message)) == (1 if damage == 'new_message' else 0)


def test_old_success_is_readable_without_inventing_a_message_id(client):
    http, sessions, _ = client
    assert '[DONE]' in http.post('/consultations/1/messages', json=BODY).text
    with sessions() as db:
        db.scalar(select(ConsultationRequest)).message_id = None
        db.commit()
    result = http.get('/consultations/1/requests/recover-key-1').json()
    assert result['status'] == 'SUCCEEDED' and result['message_id'] is None
    assert result['reply']
    assert '[DONE]' in http.post('/consultations/1/messages', json=BODY).text
    with sessions() as db: assert db.get(ConsultationPass, 1).replies_used == 1


def test_finish_rollback_keeps_pointer_messages_and_charge_atomic(client):
    _, sessions, _ = client
    request_id = reserve(sessions)
    with sessions() as db:
        assert service.finish(db, request_id, '还未提交的回复')
        assert db.get(ConsultationRequest, request_id).message_id
        db.rollback()
    with sessions() as db:
        item = db.get(ConsultationRequest, request_id)
        assert item.status == 'PENDING' and item.message_id is None
        assert db.get(ConsultationPass, 1).replies_used == 0
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_missing_recovery_column_fails_closed_without_model_call(client, monkeypatch):
    http, sessions, _ = client
    with sessions() as db:
        db.execute(text('ALTER TABLE consultation_requests DROP COLUMN baseline_message_id'))
        db.commit()
    monkeypatch.setattr('app.chat.deepseek_client.call_deepseek_stream', lambda *_, **__: pytest.fail('model must not run before migration'))
    assert http.get('/consultations/1/request').status_code == 503
    assert http.get('/consultations/1/requests/recover-key-1').status_code == 503
    assert http.post('/consultations/1/messages', json=BODY).status_code == 503
    with sessions() as db:
        assert db.get(ConsultationPass, 1).replies_used == 0
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_cached_pass_cannot_hide_a_committed_revocation(client):
    _, sessions, _ = client
    with sessions() as old:
        reading = old.get(ConsultationPass, 1)
        assert reading.status == 'ACTIVE'
        with sessions() as newer:
            newer.get(ConsultationPass, 1).status = 'REVOKED'
            newer.commit()
        with pytest.raises(service.ReadingError):
            service.reserve(old, 1, 1, 1, BODY['request_key'], BODY['message'])
        assert reading.status == 'REVOKED'


def test_cached_request_cannot_complete_after_another_worker_failed_it(client):
    _, sessions, _ = client
    request_id = reserve(sessions)
    with sessions() as old:
        item = old.get(ConsultationRequest, request_id)
        assert item.status == 'PENDING'
        with sessions() as newer:
            assert not service.finish(newer, request_id)
            newer.commit()
        assert not service.finish(old, request_id, '迟到的回复')
        old.commit()
    with sessions() as db:
        assert db.get(ConsultationPass, 1).replies_used == 0
        assert db.scalar(select(func.count()).select_from(Message)) == 0
