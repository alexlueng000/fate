"""First-report reservation/recovery contracts; no live MySQL or provider."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.db import get_db, get_db_tx
from app.deps import get_current_user_optional
from app.models.chat import Conversation, Message
from app.models.profile import UserProfile
from app.models.quota import UserQuota
from app.models.personal_report_request import PersonalReportRequest
from app.models.bazi_opening_request import BaziOpeningRequest
from app.models.chat_turn_request import ChatTurnRequest
from app.services.personal_report_request import reserve_report, report_status, mark_failed, generate_report
from app.services.completed_reply import save_completed_exchange
from app.services.conversation_report import PERSONAL_TITLES

CHART = {'gender': '男', 'solar_date': '1993-03-09 07:00:00',
         'four_pillars': {'year': ['甲', '子'], 'month': ['丙', '寅'], 'day': ['戊', '辰'], 'hour': ['庚', '午']},
         'dayun': [{'age': 8, 'start_year': 2000, 'pillar': ['丁', '卯']}]}
REPORT = '\n'.join(f'### {title}\n完整的{title}测试原文。' for title in PERSONAL_TITLES)


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'request.sqlite'}", connect_args={'check_same_thread': False, 'timeout': 10})
    for model in (UserProfile, Conversation, Message, UserQuota, PersonalReportRequest, ChatTurnRequest, BaziOpeningRequest):
        model.__table__.create(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        for uid in (1, 2):
            db.add(UserProfile(id=uid, user_id=uid, gender='male', birth_date=date(1993, 3, 9), birth_time=time(7), birth_location='上海', bazi_chart={'mingpan': CHART}))
            db.add(UserQuota(user_id=uid, quota_type='chat', total_quota=1, used_quota=0))
        db.commit()
    yield factory
    engine.dispose()


def counts(sessions):
    with sessions() as db:
        return (db.scalar(select(UserQuota.used_quota).where(UserQuota.user_id == 1)),
                db.scalar(select(func.count()).select_from(Message)),
                db.scalar(select(func.count()).select_from(Conversation)))


def complete(db, prepared):
    reservation = prepared['reservation']
    return save_completed_exchange(db, reservation['conversation_id'], reservation['user_id'], '我的命盘信息如下：报告请求',
                                   REPORT, save_profile_report=True, report_reservation=reservation)


def test_duplicate_request_and_restart_read_pending_without_second_generation(sessions):
    with sessions() as db: first = reserve_report(db, 1)
    with sessions() as db: assert reserve_report(db, 1) == {'state': 'pending'}
    with sessions() as db:
        assert report_status(db, 1) == {'state': 'pending'}
        assert report_status(db, 2) == {'state': 'idle'}
        assert db.get(PersonalReportRequest, 1).token == first['reservation']['token']
    assert counts(sessions) == (0, 0, 1)


def test_competing_first_reservations_recover_one_winner_in_isolated_database(sessions):
    def reserve(_):
        with sessions() as db: return reserve_report(db, 1)['state']
    with ThreadPoolExecutor(max_workers=4) as pool: states = list(pool.map(reserve, range(4)))
    assert states.count('reserved') == 1 and states.count('pending') == 3
    assert counts(sessions) == (0, 0, 1)


def test_completed_job_report_and_charge_commit_together_and_zero_quota_can_replay(sessions):
    with sessions() as db: first = reserve_report(db, 1)
    with sessions() as db: complete(db, first)
    with sessions() as db:
        result = reserve_report(db, 1)
        assert result['state'] == 'succeeded' and result['report'] == REPORT
        assert result['conversation_id'] == f"bazi_conv_{first['reservation']['conversation_id']}"
        assert db.get(PersonalReportRequest, 1).state == 'succeeded'
        with pytest.raises(HTTPException): complete(db, first)
    assert counts(sessions) == (1, 2, 1)


@pytest.mark.parametrize('reason', ['expired', 'failed'])
def test_retry_replaces_token_and_late_old_completion_cannot_charge(sessions, reason):
    with sessions() as db: first = reserve_report(db, 1)
    with sessions() as db:
        if reason == 'expired':
            db.get(PersonalReportRequest, 1).lease_until = datetime.utcnow() - timedelta(minutes=1)
            db.get(ChatTurnRequest, (1, first['reservation']['request_key'])).lease_until = datetime.utcnow() - timedelta(minutes=1)
            db.commit()
        else: mark_failed(db, first['reservation'])
    with sessions() as db: second = reserve_report(db, 1)
    assert first['reservation']['token'] != second['reservation']['token']
    with sessions() as db:
        with pytest.raises(HTTPException) as error: complete(db, first)
        assert error.value.status_code == 409
        mark_failed(db, first['reservation'])
        assert db.get(PersonalReportRequest, 1).state == 'pending'
        complete(db, second)
    assert counts(sessions) == (1, 2, 1)  # Retry reuses the common first conversation.


def test_profile_edit_during_generation_prevents_charge_and_stale_report(sessions):
    with sessions() as db: first = reserve_report(db, 1)
    with sessions() as db:
        db.get(UserProfile, 1).bazi_chart = {'mingpan': {**CHART, 'gender': '女'}}; db.commit()
        with pytest.raises(HTTPException) as error: complete(db, first)
        assert error.value.status_code == 409
    assert counts(sessions) == (0, 0, 1)
    with sessions() as db:
        assert db.get(UserProfile, 1).ai_report is None
        assert report_status(db, 1)['state'] == 'idle'
        assert reserve_report(db, 1)['paipan']['gender'] == '女'


@pytest.mark.parametrize('failure', ['save', 'empty', 'incomplete'])
def test_failed_completion_cannot_leave_succeeded_job_or_charge(sessions, monkeypatch, failure):
    with sessions() as db: first = reserve_report(db, 1)
    with sessions() as db:
        if failure == 'save':
            def unavailable(): raise RuntimeError('commit failed')
            monkeypatch.setattr(db, 'commit', unavailable)
        with pytest.raises((ValueError, RuntimeError)):
            save_completed_exchange(db, first['reservation']['conversation_id'], 1, '报告请求', REPORT if failure == 'save' else '' if failure == 'empty' else '### 个人画像\n半截报告',
                                    save_profile_report=True, report_reservation=first['reservation'])
    with sessions() as db:
        assert db.get(PersonalReportRequest, 1).state == 'pending' and db.get(UserProfile, 1).ai_report is None
    assert counts(sessions) == (0, 0, 1)


@pytest.fixture
def provider(sessions, monkeypatch):
    from app.chat import service
    monkeypatch.setattr('app.db.SessionLocal', sessions)
    monkeypatch.setattr(service.utils, 'load_report_system_prompt_from_db', lambda: 'configured report')
    monkeypatch.setattr(service.utils, 'build_full_system_prompt', lambda *_, **__: 'configured report')
    monkeypatch.setattr(service, 'set_conv', lambda *_, **__: None)
    monkeypatch.setattr(service, 'append_history', lambda *_, **__: None)
    calls = []
    def model(*_, **kwargs):
        assert kwargs['require_complete'] is True
        calls.append(1)
        yield REPORT
    monkeypatch.setattr(service, 'call_deepseek_stream', model)
    return service, calls


def read_stream(response):
    async def read(): return b''.join([chunk async for chunk in response.body_iterator]).decode()
    return asyncio.run(read())


@pytest.mark.parametrize('failure', [None, 'provider', 'incomplete', 'save'])
def test_stream_wrapper_marks_failure_or_success_and_retry_is_replay(sessions, provider, monkeypatch, failure):
    service, calls = provider
    request = Request({'type': 'http', 'headers': [(b'accept', b'text/event-stream')], 'query_string': b''})
    if failure in ('provider', 'incomplete'):
        def model(*_, **__):
            yield '### 个人画像\n半截内容' if failure == 'incomplete' else REPORT
            if failure == 'provider': raise RuntimeError('provider stopped')
        monkeypatch.setattr(service, 'call_deepseek_stream', model)
    if failure == 'save':
        def unavailable(*_, **__): raise RuntimeError('database unavailable')
        monkeypatch.setattr(service, '_save_db_exchange', unavailable)
    with sessions() as db: response = generate_report(db, 1, request)
    body = read_stream(response)
    with sessions() as db:
        assert db.get(PersonalReportRequest, 1).state == ('failed' if failure else 'succeeded')
        if failure:
            assert '[DONE]' not in body and '"error"' in body
            assert reserve_report(db, 1)['state'] == 'reserved'
        else:
            assert '[DONE]' in body and 'message_id' in body
            replay = generate_report(db, 1, request)
            assert '[DONE]' in read_stream(replay) and len(calls) == 1
    assert counts(sessions) == ((0, 0, 1) if failure else (1, 2, 1))


def test_pending_http_request_never_calls_provider_and_status_requires_owner(sessions, provider):
    _, calls = provider
    from app.routers.chat import router
    with sessions() as db: reserve_report(db, 1)
    identity = {'id': 1}
    app = FastAPI(); app.include_router(router)
    def dependency():
        with sessions() as db: yield db
    app.dependency_overrides[get_db] = dependency; app.dependency_overrides[get_db_tx] = dependency
    app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(id=identity['id']) if identity['id'] else None
    with TestClient(app) as client:
        assert client.post('/chat/start', json={'personal_report': True}).status_code == 409
        assert client.get('/chat/report/status').json() == {'state': 'pending'}
        identity['id'] = 2
        assert client.get('/chat/report/status').json() == {'state': 'idle'}
        identity['id'] = None
        assert client.get('/chat/report/status').status_code == 401
        assert client.post('/chat/start', json={'personal_report': True}).status_code == 400
    assert calls == [] and counts(sessions) == (0, 0, 1)


def test_disconnect_before_model_reply_releases_only_its_own_reservation(sessions, provider):
    _, calls = provider
    request = Request({'type': 'http', 'headers': [(b'accept', b'text/event-stream')], 'query_string': b''})
    with sessions() as db: response = generate_report(db, 1, request)
    async def disconnect():
        first = await response.body_iterator.__anext__()
        assert b'conversation_id' in first
        await response.body_iterator.aclose()
    asyncio.run(disconnect())
    with sessions() as db:
        assert report_status(db, 1) == {'state': 'failed'}
        assert reserve_report(db, 1)['state'] == 'reserved'
    assert calls == [] and counts(sessions) == (0, 0, 1)


def test_reservation_transaction_failure_keeps_no_orphan_generation(sessions, monkeypatch):
    with sessions() as db:
        def unavailable(): raise RuntimeError('database unavailable')
        monkeypatch.setattr(db, 'commit', unavailable)
        with pytest.raises(RuntimeError): reserve_report(db, 1)
    assert counts(sessions) == (0, 0, 0)
    with sessions() as db: assert report_status(db, 1) == {'state': 'idle'}


@pytest.mark.parametrize('titles', [PERSONAL_TITLES, ['核心观察', '分析依据', '现实建议']])
def test_short_content_under_complete_report_heading_is_not_merged_into_title(titles):
    from app.chat.markdown_utils import normalize_markdown
    from app.services.conversation_report import report_sections
    raw = '\n'.join(f'### {title}\n谨慎。' for title in titles)
    sections = report_sections(normalize_markdown(raw))
    assert [section['title'] for section in sections] == titles
    assert all(section['body'] == '谨慎。' for section in sections)
