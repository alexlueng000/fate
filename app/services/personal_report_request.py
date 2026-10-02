"""Reserve generation without holding SQL locks while waiting for the model."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.chat import Conversation
from app.models.profile import UserProfile
from app.models.personal_report_request import PersonalReportRequest
from app.services.quota import QuotaService

LEASE_MINUTES = 10


def chart_hash(chart):
    chart = chart or {}
    return hashlib.sha256(json.dumps(chart.get('mingpan', chart), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def report_status(db, user_id):
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if not profile:
        raise HTTPException(400, '请先完善个人档案')
    if profile.ai_report:
        from app.routers.profile import _report_source
        source = _report_source(db, profile)
        return {'state': 'succeeded', 'report': profile.ai_report,
                'conversation_id': f'bazi_conv_{source.conversation_id}' if source else None}
    job = db.get(PersonalReportRequest, profile.id)
    if job and job.user_id == user_id and job.chart_hash == chart_hash(profile.bazi_chart):
        return {'state': 'pending' if job.state == 'pending' and job.lease_until > datetime.utcnow() else 'failed'}
    return {'state': 'idle'}


def reserve_report(db, user_id):
    """Serialize short reservation transactions on the existing profile row."""
    try:
        # Match completion's quota -> profile -> request lock order. An existing
        # report or pending request is readable even with zero remaining uses.
        allowed, message, _ = QuotaService.check_available(db, user_id, 'chat', commit=False)
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id)
                            .with_for_update().execution_options(populate_existing=True))
        if not profile:
            raise HTTPException(400, '请先完善个人档案')
        if profile.ai_report:
            result = report_status(db, user_id)
            db.commit()
            return result
        chart = profile.bazi_chart or {}
        snapshot = chart.get('mingpan', chart)
        if not snapshot.get('four_pillars') or not snapshot.get('dayun'):
            raise HTTPException(400, '档案尚未保存完整命盘，请检查出生信息。')
        digest = chart_hash(chart)
        job = db.scalar(select(PersonalReportRequest).where(PersonalReportRequest.profile_id == profile.id)
                        .with_for_update().execution_options(populate_existing=True))
        now = datetime.utcnow()
        if job and job.user_id == user_id and job.chart_hash == digest and job.state == 'pending' and job.lease_until > now:
            db.commit()
            return {'state': 'pending'}
        if not allowed:
            raise HTTPException(429, message)
        conversation = Conversation(user_id=user_id, profile_id=profile.id, title='个人命盘报告', bazi_chart_snapshot=snapshot)
        db.add(conversation); db.flush()
        if not job:
            job = PersonalReportRequest(profile_id=profile.id)
            db.add(job)
        job.user_id = user_id; job.chart_hash = digest; job.state = 'pending'; job.token = uuid.uuid4().hex
        job.conversation_id = conversation.id; job.lease_until = now + timedelta(minutes=LEASE_MINUTES); job.updated_at = now
        reservation = {'profile_id': profile.id, 'user_id': user_id, 'token': job.token,
                       'conversation_id': conversation.id, 'chart_hash': digest}
        db.commit()
        return {'state': 'reserved', 'reservation': reservation, 'paipan': snapshot}
    except IntegrityError:
        db.rollback()
        # A unique-key race in an installation without effective row locking
        # can still recover the winning reservation without another model call.
        current = report_status(db, user_id)
        if current['state'] in ('pending', 'succeeded'):
            db.commit()
            return current
        raise
    except Exception:
        db.rollback()
        raise


def validate_completion(db, conversation, reservation):
    """Validate before charge commits; replaced workers cannot save or consume."""
    # Follow completed_reply's quota -> profile ordering; reservation never
    # touches a pre-existing conversation, avoiding a reversed lock cycle.
    profile = db.scalar(select(UserProfile).where(UserProfile.id == reservation['profile_id'],
                                                 UserProfile.user_id == conversation.user_id)
                        .with_for_update().execution_options(populate_existing=True))
    job = db.scalar(select(PersonalReportRequest).where(PersonalReportRequest.profile_id == reservation['profile_id'])
                    .with_for_update().execution_options(populate_existing=True))
    if (not profile or not job or job.user_id != conversation.user_id or job.token != reservation['token']
            or job.state != 'pending' or job.conversation_id != conversation.id
            or chart_hash(profile.bazi_chart) != reservation['chart_hash']
            or job.chart_hash != reservation['chart_hash']):
        raise HTTPException(409, '报告生成状态或命盘已发生变化，请重新加载查看最新报告。')
    return job


def mark_failed(db, reservation):
    try:
        job = db.scalar(select(PersonalReportRequest).where(PersonalReportRequest.profile_id == reservation['profile_id'])
                        .with_for_update().execution_options(populate_existing=True))
        if job and job.token == reservation['token'] and job.state == 'pending':
            job.state = 'failed'; job.updated_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        # Unknown failure is left pending until the lease expires; never guess
        # success or release a newer worker's reservation.
        from app.core.logging import get_logger
        get_logger('personal_report').warning('reservation_failure_state_unavailable')


def generate_report(db, user_id, request):
    from fastapi.responses import StreamingResponse
    from sqlalchemy.exc import SQLAlchemyError
    from app.chat.service import start_chat
    from app.chat.sse import sse_pack, sse_response, should_stream
    try:
        prepared = reserve_report(db, user_id)
    except SQLAlchemyError as error:
        from app.core.logging import get_logger
        get_logger('personal_report').error('request_storage_unavailable', error=str(error), migration='2026-10-03_personal_report_requests.sql')
        raise HTTPException(503, '报告服务暂不可用，请稍后重新加载。') from error
    if prepared['state'] == 'pending':
        raise HTTPException(409, '同一命盘的报告正在生成，请等待保存结果。')
    if prepared['state'] == 'succeeded':
        if not should_stream(request):
            return prepared.get('conversation_id') or '', prepared['report']
        def replay():
            if prepared.get('conversation_id'):
                yield sse_pack(json.dumps({'meta': {'conversation_id': prepared['conversation_id']}}, ensure_ascii=False))
            yield sse_pack(json.dumps({'text': prepared['report'], 'replace': True}, ensure_ascii=False))
            yield sse_pack('[DONE]')
        return sse_response(replay)
    reservation = prepared['reservation']
    try:
        result = start_chat(prepared['paipan'], None, 0, request, user_id=user_id, db=db,
                            profile_id=reservation['profile_id'], report_reservation=reservation)
    except Exception:
        mark_failed(db, reservation)
        raise
    if not isinstance(result, StreamingResponse):
        return result
    async def track_completion():
        try:
            async for chunk in result.body_iterator:
                yield chunk
        finally:
            from app.db import SessionLocal
            with SessionLocal() as fresh:
                mark_failed(fresh, reservation)
    return StreamingResponse(track_completion(), headers=dict(result.headers), status_code=result.status_code)
