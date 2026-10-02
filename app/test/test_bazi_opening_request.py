"""First Bazi report recovery using isolated file transactions, not live AI."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.ext.compiler import compiles

from app.test.test_completed_reply import sessions, stats, CHART, PERSONAL_ANSWER
from app.models.bazi_opening_request import BaziOpeningRequest
from app.models.chat import Conversation, Message
from app.models.chat_turn_request import ChatTurnRequest
from app.models.guest_analysis import GuestAnalysis
from app.models.profile import UserProfile
from app.models.personal_report_request import PersonalReportRequest
from app.schemas.chat import ChatStartReq
from app.services.bazi_opening_request import reserve_opening, opening_status, generate_opening
from app.services.chat_turn_request import mark_failed
from app.services.completed_reply import save_completed_exchange


@compiles(MEDIUMTEXT, 'sqlite')
def _guest_text_for_isolated_sqlite(type_, compiler, **kwargs):
    return 'TEXT'


@pytest.fixture
def openings(sessions):
    with sessions() as db:
        for model in (ChatTurnRequest, BaziOpeningRequest, PersonalReportRequest, GuestAnalysis):
            model.__table__.create(db.get_bind())
        db.add(GuestAnalysis(id=1, public_id='owned-guest', guest_session_id='guest-session', user_id=1,
            status='succeeded', gender='female', birth_date=date(1993, 3, 9), birth_time=time(7), birth_location='上海',
            bazi_result={'mingpan': {**CHART, 'gender': '女'}}, expires_at=datetime.utcnow() + timedelta(days=1)))
        db.commit()
    return sessions


def finish(db, reservation):
    return save_completed_exchange(db, reservation['conversation_id'], 1, '我的命盘信息如下：首次报告',
        PERSONAL_ANSWER, save_profile_report=True, turn_reservation=reservation)


def test_two_tabs_reserve_one_first_report_and_do_not_spend_before_save(openings):
    def attempt(_):
        with openings() as db:
            return reserve_opening(db, 1, ChatStartReq())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(result['state'] for result in results) == ['pending', 'reserved']
    assert len({result['conversation_id'] for result in results}) == 1
    with openings() as db:
        assert db.scalar(select(func.count()).select_from(BaziOpeningRequest)) == 1
        assert db.scalar(select(func.count()).select_from(ChatTurnRequest)) == 1
        assert db.scalar(select(func.count()).select_from(Conversation)) == 3
    assert stats(openings) == (0, 0)


def test_saved_first_report_replays_at_zero_quota_and_does_not_replace_with_follow_up(openings):
    with openings() as db:
        first = reserve_opening(db, 1, ChatStartReq())
        mid = finish(db, first['reservation'])
        db.add(Message(conversation_id=first['reservation']['conversation_id'], user_id=1, role='assistant', content='后续回答'))
        db.commit()
    with openings() as db:
        replay = reserve_opening(db, 1, ChatStartReq(kb_topk=3, kb_index_dir='changed-setting'))
        assert replay['state'] == 'succeeded' and replay['message_id'] == mid and replay['reply'] == PERSONAL_ANSWER
        assert replay['payload']['kb_topk'] == 0 and replay['payload']['kb_index_dir'] is None
        assert opening_status(db, 1, ChatStartReq())['message_id'] == mid
    assert stats(openings) == (1, 3)


@pytest.mark.parametrize('reason', ['failed', 'expired'])
def test_retry_preserves_original_chart_context_settings_and_rejects_late_worker(openings, reason):
    original = {'facts': {'topic': '职业方向', 'currentSituation': '仍在原公司'}}
    with openings() as db:
        first = reserve_opening(db, 1, ChatStartReq(task_context=original, kb_topk=2))
        if reason == 'failed':
            mark_failed(db, first['reservation'])
        else:
            db.get(ChatTurnRequest, (1, first['request_key'])).lease_until = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        db.get(UserProfile, 1).bazi_chart = {'mingpan': {**CHART, 'gender': '女'}}
        db.commit()
        status = opening_status(db, 1, conversation_id=first['conversation_id'])
        assert status['state'] == 'retryable' and status['paipan'] == CHART and status['task_context'] == original
        retry = reserve_opening(db, 1, None, conversation_id=first['conversation_id'])
        assert retry['request_key'] == first['request_key'] and retry['conversation_id'] == first['conversation_id']
        assert retry['payload'] == first['payload']
        with pytest.raises(HTTPException):
            finish(db, first['reservation'])
        mark_failed(db, first['reservation'])
        assert opening_status(db, 1, conversation_id=first['conversation_id'])['state'] == 'pending'
        finish(db, retry['reservation'])
        assert db.get(UserProfile, 1).ai_report is None  # Do not cache old chart's report on the new profile.
    assert stats(openings) == (1, 2)


def test_different_charts_or_explicit_backgrounds_have_separate_first_reports(openings):
    with openings() as db:
        first = reserve_opening(db, 1, ChatStartReq())
        changed_facts = reserve_opening(db, 1, ChatStartReq(task_context={'facts': {'topic': '换一个问题'}}))
        db.get(UserProfile, 1).bazi_chart = {'mingpan': {**CHART, 'gender': '女'}}; db.commit()
        changed_chart = reserve_opening(db, 1, ChatStartReq())
        assert len({value['conversation_id'] for value in (first, changed_facts, changed_chart)}) == 3
        assert opening_status(db, 1, ChatStartReq())['conversation_id'] == changed_chart['conversation_id']
    assert stats(openings) == (0, 0)


def test_bound_guest_uses_its_own_chart_and_does_not_attach_unrelated_profile(openings):
    with openings() as db:
        guest = reserve_opening(db, 1, ChatStartReq(guest_analysis_public_id='owned-guest', paipan=CHART))
        profile = reserve_opening(db, 1, ChatStartReq())
        assert guest['payload']['paipan']['gender'] == '女' and guest['profile_id'] is None
        assert guest['conversation_id'] != profile['conversation_id']
        assert db.get(Conversation, guest['reservation']['conversation_id']).profile_id is None
        finish(db, guest['reservation'])
        replay = reserve_opening(db, 1, ChatStartReq(guest_analysis_public_id='owned-guest'))
        assert replay['state'] == 'succeeded' and replay['conversation_id'] == guest['conversation_id']
        assert db.get(UserProfile, 1).ai_report is None


@pytest.mark.parametrize('invalid', ['owner', 'unfinished', 'expired', 'missing-chart'])
def test_guest_source_must_be_owned_complete_valid_and_unexpired(openings, invalid):
    with openings() as db:
        guest = db.get(GuestAnalysis, 1)
        if invalid == 'owner': guest.user_id = 2
        if invalid == 'unfinished': guest.status = 'running'
        if invalid == 'expired': guest.expires_at = datetime.utcnow() - timedelta(seconds=1)
        if invalid == 'missing-chart': guest.bazi_result = {}
        db.commit()
        for operation in (opening_status, reserve_opening):
            with pytest.raises(HTTPException) as error:
                operation(db, 1, ChatStartReq(guest_analysis_public_id='owned-guest'))
            assert error.value.status_code == (404 if invalid == 'owner' else 400)
        assert db.scalar(select(func.count()).select_from(BaziOpeningRequest)) == 0
    assert stats(openings) == (0, 0)


def test_status_is_read_only_and_other_user_cannot_locate_or_retry(openings):
    with openings() as db:
        assert opening_status(db, 1, ChatStartReq())['state'] == 'idle'
        assert db.scalar(select(func.count()).select_from(BaziOpeningRequest)) == 0
        first = reserve_opening(db, 1, ChatStartReq())
        for operation in (opening_status, reserve_opening):
            with pytest.raises(HTTPException) as error:
                operation(db, 2, conversation_id=first['conversation_id'])
            assert error.value.status_code == 404
        assert opening_status(db, 1, conversation_id='bazi_conv_1')['state'] == 'idle'
        with pytest.raises(HTTPException): opening_status(db, 1, conversation_id='2')  # Liuyao
        assert opening_status(db, 1, ChatStartReq())['state'] == 'pending'
    assert stats(openings) == (0, 0)


def test_legacy_seven_chapter_opening_replays_but_ordinary_follow_up_does_not(openings):
    with openings() as db:
        db.add_all([Message(conversation_id=1, user_id=1, role='user', content='普通问题'),
                    Message(conversation_id=1, user_id=1, role='assistant', content=PERSONAL_ANSWER)])
        db.commit()
        assert opening_status(db, 1, ChatStartReq())['state'] == 'idle'
        db.query(Message).delete(); db.commit()
        mid = save_completed_exchange(db, 1, 1, '我的命盘信息如下：原报告', PERSONAL_ANSWER, save_profile_report=True)
        result = reserve_opening(db, 1, ChatStartReq())
        assert result['state'] == 'succeeded' and result['message_id'] == mid and result['conversation_id'] == 'bazi_conv_1'
        assert db.scalar(select(func.count()).select_from(BaziOpeningRequest)) == 0
    assert stats(openings) == (1, 2)


def test_commit_failure_does_not_leave_half_created_opening(openings, monkeypatch):
    with openings() as db:
        def fail(): raise RuntimeError('commit failed')
        monkeypatch.setattr(db, 'commit', fail)
        with pytest.raises(RuntimeError): reserve_opening(db, 1, ChatStartReq())
    with openings() as db:
        assert db.scalar(select(func.count()).select_from(BaziOpeningRequest)) == 0
        assert db.scalar(select(func.count()).select_from(ChatTurnRequest)) == 0
        assert db.scalar(select(func.count()).select_from(Conversation)) == 2


def test_changed_history_cannot_be_rebased_into_a_late_first_report(openings):
    with openings() as db:
        first = reserve_opening(db, 1, ChatStartReq())
        mark_failed(db, first['reservation'])
        db.add(Message(conversation_id=first['reservation']['conversation_id'], user_id=1, role='user', content='另一条已保存的问题'))
        db.commit()
        with pytest.raises(HTTPException) as error:
            reserve_opening(db, 1, None, conversation_id=first['conversation_id'])
        assert error.value.status_code == 409


def test_retry_provider_receives_saved_facts_as_user_data_and_original_chart(openings, monkeypatch):
    from app.chat import service
    monkeypatch.setattr('app.db.SessionLocal', openings)
    monkeypatch.setattr(service.utils, 'load_report_system_prompt_from_db', lambda: 'configured')
    monkeypatch.setattr(service.utils, 'build_full_system_prompt', lambda *_, **__: 'configured')
    monkeypatch.setattr(service, 'set_conv', lambda *_: None)
    monkeypatch.setattr(service, 'append_history', lambda *_: None)
    monkeypatch.setattr(service, 'should_stream', lambda _: True)
    with openings() as db:
        first = reserve_opening(db, 1, ChatStartReq(task_context={'taskType': 'career', 'facts': {'topic': '原问题', 'currentSituation': '明确的原背景'}}))
        mark_failed(db, first['reservation'])
        db.get(UserProfile, 1).bazi_chart = {'mingpan': {**CHART, 'gender': '女'}}; db.commit()
    def provider(messages, **kwargs):
        assert kwargs['require_complete']
        assert messages[0] == {'role': 'system', 'content': 'configured'}
        assert '性别：男' in messages[1]['content']
        assert messages[2]['role'] == 'user' and '明确的原背景' in messages[2]['content']
        yield PERSONAL_ANSWER
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    async def read():
        with openings() as db:
            response = generate_opening(db, 1, None, None, conversation_id=first['conversation_id'])
            return b''.join([chunk async for chunk in response.body_iterator]).decode()
    assert '[DONE]' in asyncio.run(read())
    assert stats(openings) == (1, 2)


@pytest.mark.parametrize('failure', [False, True])
def test_actual_stream_saves_same_reservation_or_releases_for_manual_retry(openings, monkeypatch, failure):
    from app.chat import service
    monkeypatch.setattr('app.db.SessionLocal', openings)
    monkeypatch.setattr(service.utils, 'load_report_system_prompt_from_db', lambda: 'configured')
    monkeypatch.setattr(service.utils, 'build_full_system_prompt', lambda *_, **__: 'configured')
    monkeypatch.setattr(service, 'set_conv', lambda *_: None)
    monkeypatch.setattr(service, 'append_history', lambda *_: None)
    monkeypatch.setattr(service, 'should_stream', lambda _: True)
    def provider(*_, **kwargs):
        assert kwargs['require_complete']
        if failure: raise RuntimeError('model failed')
        yield PERSONAL_ANSWER
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    async def read():
        with openings() as db:
            response = generate_opening(db, 1, ChatStartReq(), None)
            return b''.join([chunk async for chunk in response.body_iterator]).decode()
    body = asyncio.run(read())
    with openings() as db:
        assert opening_status(db, 1, ChatStartReq())['state'] == ('retryable' if failure else 'succeeded')
        assert db.scalar(select(func.count()).select_from(Conversation)) == 3
    assert ('[DONE]' in body) == (not failure)
    assert stats(openings) == ((0, 0) if failure else (1, 2))


def test_http_lookup_retry_replay_and_missing_table_never_generate_unprotected(openings, monkeypatch):
    from app.routers import chat
    from app.chat import service
    from app.db import get_db, get_db_tx
    from app.deps import get_current_user_optional
    calls = []
    def provider(*args, **kwargs):
        calls.append(1)
        reservation = kwargs['turn_reservation']
        finish(kwargs['db'], reservation)
        return f"bazi_conv_{reservation['conversation_id']}", PERSONAL_ANSWER
    monkeypatch.setattr(service, 'start_chat', provider)
    app = FastAPI(); app.include_router(chat.router)
    def dependency():
        with openings() as db: yield db
    for dep in (get_db, get_db_tx): app.dependency_overrides[dep] = dependency
    app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        assert client.post('/chat/start/status', json={}).json()['state'] == 'idle'
        for _ in range(2):
            response = client.post('/chat/start', json={})
            assert response.status_code == 200, response.text
        cid = response.json()['conversation_id']
        assert client.get(f'/chat/conversations/{cid}/opening').json()['state'] == 'succeeded'
        assert client.post(f'/chat/conversations/{cid}/opening').status_code == 200
        with openings() as db: BaziOpeningRequest.__table__.drop(db.get_bind())
        assert client.post('/chat/start', json={}).status_code == 503
        assert client.post('/chat/start/status', json={}).status_code == 503
        assert client.get(f'/chat/conversations/{cid}/opening').status_code == 503
    assert len(calls) == 1 and stats(openings) == (1, 2)
