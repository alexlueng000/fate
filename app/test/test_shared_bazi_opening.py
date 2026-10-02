"""Cross-page first-report contracts with file SQLite and a fixed provider."""
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.requests import Request

from app.test.test_bazi_opening_request import openings, finish
from app.test.test_completed_reply import sessions, CHART, PERSONAL_ANSWER, stats
from app.models.bazi_opening_request import BaziOpeningRequest
from app.models.chat import Conversation, Message
from app.models.chat_turn_request import ChatTurnRequest
from app.models.personal_report_request import PersonalReportRequest
from app.models.profile import UserProfile
from app.models.quota import UserQuota
from app.schemas.chat import ChatStartReq
from app.services.bazi_opening_request import opening_status, reserve_opening, generate_opening
from app.services.personal_report_request import reserve_report, report_status, mark_failed, chart_hash, generate_report
from app.services.completed_reply import save_completed_exchange
from app.services.conversation_report import report_sections, PERSONAL_TITLES


@pytest.mark.parametrize('first_page', ['personal', 'chat'])
def test_either_page_reserves_first_and_the_other_reads_the_same_slot(openings, first_page):
    with openings() as db:
        first = reserve_report(db, 1) if first_page == 'personal' else reserve_opening(db, 1, ChatStartReq())
        cid = first['reservation']['conversation_id']
    with openings() as db:
        assert reserve_report(db, 1) == {'state': 'pending'}
        assert reserve_opening(db, 1, ChatStartReq())['conversation_id'] == f'bazi_conv_{cid}'
        assert report_status(db, 1) == {'state': 'pending'}
        assert opening_status(db, 1, ChatStartReq())['state'] == 'pending'
        assert db.scalar(select(func.count()).select_from(BaziOpeningRequest)) == 1
        assert db.scalar(select(func.count()).select_from(ChatTurnRequest)) == 1
        assert db.get(PersonalReportRequest, 1).token == first['reservation']['token']
    assert stats(openings) == (0, 0)


def test_six_simultaneous_requests_across_both_pages_have_one_winner(openings):
    def attempt(index):
        with openings() as db:
            return (reserve_report(db, 1) if index % 2 else reserve_opening(db, 1, ChatStartReq()))['state']
    with ThreadPoolExecutor(max_workers=6) as pool:
        states = list(pool.map(attempt, range(6)))
    assert states.count('reserved') == 1 and states.count('pending') == 5
    with openings() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 3  # two unrelated fixture records
        assert db.scalar(select(func.count()).select_from(BaziOpeningRequest)) == 1
    assert stats(openings) == (0, 0)


@pytest.mark.parametrize('first_page', ['personal', 'chat'])
def test_both_pages_replay_the_same_initial_report_at_zero_quota(openings, first_page):
    with openings() as db:
        prepared = reserve_report(db, 1) if first_page == 'personal' else reserve_opening(db, 1, ChatStartReq())
        reservation = prepared['reservation']
        mid = save_completed_exchange(db, reservation['conversation_id'], 1, '我的命盘信息如下：首次报告', PERSONAL_ANSWER,
            save_profile_report=True, **({'report_reservation': reservation} if first_page == 'personal' else {'turn_reservation': reservation}))
        db.add(Message(conversation_id=reservation['conversation_id'], user_id=1, role='assistant', content='后续回答，不是原报告'))
        db.commit()
    with openings() as db:
        personal = reserve_report(db, 1)
        chat = reserve_opening(db, 1, ChatStartReq())
        assert personal['report'] == chat['reply'] == PERSONAL_ANSWER
        assert personal['conversation_id'] == chat['conversation_id'] == f"bazi_conv_{reservation['conversation_id']}"
        assert chat['message_id'] == mid
        assert db.get(PersonalReportRequest, 1).state == 'succeeded'
        assert db.get(ChatTurnRequest, (1, reservation['request_key'])).state == 'succeeded'
    assert stats(openings) == (1, 3)


@pytest.mark.parametrize('first_page', ['personal', 'chat'])
def test_failed_request_can_change_page_without_changing_source_or_key(openings, first_page):
    with openings() as db:
        first = reserve_report(db, 1) if first_page == 'personal' else reserve_opening(db, 1, ChatStartReq(kb_topk=2))
        reservation = first['reservation']
        mark_failed(db, reservation)
    with openings() as db:
        assert report_status(db, 1) == {'state': 'failed'}
        assert opening_status(db, 1, ChatStartReq())['state'] == 'retryable'
        retry = reserve_opening(db, 1, ChatStartReq()) if first_page == 'personal' else reserve_report(db, 1)
        newer = retry['reservation']
        assert newer['request_key'] == reservation['request_key'] and newer['conversation_id'] == reservation['conversation_id']
        assert newer['token'] != reservation['token']
        if first_page == 'chat': assert retry['kb_topk'] == 2
        with pytest.raises(HTTPException): finish(db, reservation)
        mark_failed(db, reservation)
        assert report_status(db, 1) == {'state': 'pending'}
        finish(db, newer)
    assert stats(openings) == (1, 2)


def legacy_job(db, state='pending'):
    now = datetime.utcnow()
    # A worker started before the common request table was introduced.
    db.add(PersonalReportRequest(profile_id=1, user_id=1, conversation_id=1, token='legacy-token',
        state=state, chart_hash=chart_hash(CHART), lease_until=now + timedelta(minutes=10), updated_at=now))
    db.commit()


def test_pre_upgrade_pending_personal_report_blocks_both_pages_until_saved(openings):
    with openings() as db:
        legacy_job(db)
        assert reserve_report(db, 1) == {'state': 'pending'}
        assert reserve_opening(db, 1, ChatStartReq())['state'] == 'pending'
        assert opening_status(db, 1, conversation_id='bazi_conv_1')['state'] == 'pending'
        assert db.scalar(select(func.count()).select_from(BaziOpeningRequest)) == 0
        reservation = {'profile_id': 1, 'user_id': 1, 'conversation_id': 1, 'token': 'legacy-token', 'chart_hash': chart_hash(CHART)}
        mid = save_completed_exchange(db, 1, 1, '我的命盘信息如下：旧报告请求', PERSONAL_ANSWER,
            save_profile_report=True, report_reservation=reservation)
    with openings() as db:
        result = opening_status(db, 1, conversation_id='bazi_conv_1')
        assert result['state'] == 'succeeded' and result['message_id'] == mid
        assert reserve_report(db, 1)['conversation_id'] == 'bazi_conv_1'
        assert reserve_opening(db, 1, ChatStartReq())['message_id'] == mid
    assert stats(openings) == (1, 2)


def test_expired_pre_upgrade_worker_cannot_save_after_the_shared_replacement(openings):
    with openings() as db:
        legacy_job(db)
        job = db.get(PersonalReportRequest, 1)
        job.lease_until = datetime.utcnow() - timedelta(seconds=1); db.commit()
        old = {'profile_id': 1, 'user_id': 1, 'conversation_id': 1, 'token': 'legacy-token', 'chart_hash': chart_hash(CHART)}
        with pytest.raises(HTTPException):
            save_completed_exchange(db, 1, 1, '我的命盘信息如下：迟到请求', PERSONAL_ANSWER, save_profile_report=True, report_reservation=old)
        retry = reserve_opening(db, 1, None, conversation_id='bazi_conv_1')
        assert retry['state'] == 'reserved'
        with pytest.raises(HTTPException):
            save_completed_exchange(db, 1, 1, '我的命盘信息如下：旧请求', PERSONAL_ANSWER, save_profile_report=True, report_reservation=old)
        finish(db, retry['reservation'])
    assert stats(openings) == (1, 2)


def test_topic_and_guest_openings_cannot_replace_the_personal_report_cache(openings):
    with openings() as db:
        db.scalar(select(UserQuota).where(UserQuota.quota_type == 'chat')).total_quota = 3
        # Match the guest chart to the profile: ownership alone must not allow
        # that separate public source to replace the common profile report.
        from app.models.guest_analysis import GuestAnalysis
        db.get(GuestAnalysis, 1).bazi_result = {'mingpan': CHART}; db.commit()
        personal = reserve_report(db, 1)
        topic = reserve_opening(db, 1, ChatStartReq(task_context={'taskType': 'career', 'facts': {'topic': '另一个专题'}}))
        guest = reserve_opening(db, 1, ChatStartReq(guest_analysis_public_id='owned-guest'))
        assert len({value['reservation']['conversation_id'] for value in (personal, topic, guest)}) == 3
        finish(db, topic['reservation']); finish(db, guest['reservation'])
        assert db.get(UserProfile, 1).ai_report is None
        assert report_status(db, 1) == {'state': 'pending'}
        finish(db, personal['reservation'])
        assert reserve_report(db, 1)['conversation_id'] == f"bazi_conv_{personal['reservation']['conversation_id']}"
    assert stats(openings) == (3, 6)


def test_shared_binding_failure_releases_retry_slot_without_charging(openings, monkeypatch):
    import app.services.bazi_opening_request as service
    with openings() as db:
        first = reserve_opening(db, 1, ChatStartReq())
        mark_failed(db, first['reservation'])
        def fail(*_, **__): raise RuntimeError('profile guard storage failed')
        monkeypatch.setattr(service, '_bind_report_job', fail)
        with pytest.raises(RuntimeError): reserve_report(db, 1)
    with openings() as db:
        assert opening_status(db, 1, ChatStartReq())['state'] == 'retryable'
    assert stats(openings) == (0, 0)


@pytest.mark.parametrize('first_page', ['personal', 'chat'])
@pytest.mark.parametrize('outcome', ['complete', 'disconnect'])
def test_actual_inflight_stream_is_shared_and_disconnect_releases_for_the_other_page(openings, monkeypatch, first_page, outcome):
    from app.chat import service
    monkeypatch.setattr('app.db.SessionLocal', openings)
    monkeypatch.setattr(service.utils, 'load_report_system_prompt_from_db', lambda: 'configured')
    monkeypatch.setattr(service.utils, 'build_full_system_prompt', lambda *_, **__: 'configured')
    monkeypatch.setattr(service, 'set_conv', lambda *_: None)
    monkeypatch.setattr(service, 'append_history', lambda *_: None)
    calls = []
    def provider(*_, **kwargs):
        assert kwargs['require_complete']; calls.append(1); yield PERSONAL_ANSWER
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    request = Request({'type': 'http', 'headers': [(b'accept', b'text/event-stream')], 'query_string': b''})
    with openings() as db:
        response = generate_report(db, 1, request) if first_page == 'personal' else generate_opening(db, 1, ChatStartReq(), request)
    async def read():
        first = await response.body_iterator.__anext__()
        assert b'conversation_id' in first and calls == []
        with openings() as db:
            assert reserve_report(db, 1)['state'] == 'pending'
            assert reserve_opening(db, 1, ChatStartReq())['state'] == 'pending'
        if outcome == 'disconnect':
            await response.body_iterator.aclose()
            return ''
        return b''.join([chunk async for chunk in response.body_iterator]).decode()
    body = asyncio.run(read())
    with openings() as db:
        assert report_status(db, 1)['state'] == ('succeeded' if outcome == 'complete' else 'failed')
        if outcome == 'disconnect':
            retry = reserve_opening(db, 1, ChatStartReq()) if first_page == 'personal' else reserve_report(db, 1)
            assert retry['state'] == 'reserved'
            assert db.scalar(select(func.count()).select_from(Conversation)) == 3
    assert calls == ([1] if outcome == 'complete' else [])
    assert ('[DONE]' in body) == (outcome == 'complete')
    assert stats(openings) == ((1, 2) if outcome == 'complete' else (0, 0))


def test_http_two_entry_modes_use_one_actual_provider_and_one_saved_report(openings, monkeypatch):
    from app.chat import service
    from app.db import get_db, get_db_tx
    from app.deps import get_current_user_optional
    from app.routers.chat import router
    monkeypatch.setattr('app.db.SessionLocal', openings)
    monkeypatch.setattr(service.utils, 'load_report_system_prompt_from_db', lambda: 'configured')
    monkeypatch.setattr(service.utils, 'build_full_system_prompt', lambda *_, **__: 'configured')
    monkeypatch.setattr(service, 'set_conv', lambda *_: None)
    monkeypatch.setattr(service, 'append_history', lambda *_: None)
    calls = []
    def provider(*_, **kwargs):
        assert kwargs['require_complete']; calls.append(1); yield PERSONAL_ANSWER
    monkeypatch.setattr(service, 'call_deepseek_stream', provider)
    app = FastAPI(); app.include_router(router)
    def dependency():
        with openings() as db: yield db
    for dep in (get_db, get_db_tx): app.dependency_overrides[dep] = dependency
    app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        delivered = []
        for payload in ({'personal_report': True}, {}, {'personal_report': True}):
            result = client.post('/chat/start', json=payload, headers={'Accept': 'text/event-stream'})
            assert result.status_code == 200 and '[DONE]' in result.text, result.text
            texts = [json.loads(line[6:])['text'] for line in result.text.splitlines()
                     if line.startswith('data: {') and '"text"' in line]
            delivered.append(texts[-1])
        saved = client.get('/chat/report/status').json()['report']
        assert [section['title'] for section in report_sections(saved)] == PERSONAL_TITLES
        assert delivered == [saved] * 3
        assert client.post('/chat/start/status', json={}).json()['reply'] == saved
    assert len(calls) == 1 and stats(openings) == (1, 2)
