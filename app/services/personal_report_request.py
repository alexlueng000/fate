"""Reserve generation without holding SQL locks while waiting for the model."""
import hashlib
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from app.models.profile import UserProfile
from app.models.personal_report_request import PersonalReportRequest

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
    # Both pages resolve the same owned chart and common first-request slot.
    # The legacy personal row is still read by opening_status until its worker
    # finishes or expires; no read creates or adopts a new generation.
    from app.schemas.chat import ChatStartReq
    from app.services.bazi_opening_request import opening_status
    status = opening_status(db, user_id, ChatStartReq())
    if status['state'] == 'succeeded':
        return {'state': 'succeeded', 'report': status['reply'], 'conversation_id': status['conversation_id']}
    return {'state': 'failed' if status['state'] == 'retryable' else status['state']}


def reserve_report(db, user_id):
    """Use the ordinary opening's unique source slot plus profile validation."""
    from app.schemas.chat import ChatStartReq
    from app.services.bazi_opening_request import reserve_opening
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if not profile:
        raise HTTPException(400, '请先完善个人档案')
    if profile.ai_report:
        result = report_status(db, user_id)
        db.commit()
        return result
    prepared = reserve_opening(db, user_id, ChatStartReq())
    if prepared['state'] == 'pending':
        return {'state': 'pending'}
    if prepared['state'] == 'succeeded':
        return {'state': 'succeeded', 'report': prepared['reply'], 'conversation_id': prepared['conversation_id']}
    reservation = prepared['reservation']
    if not reservation.get('profile_id'):
        from app.services.chat_turn_request import mark_failed as fail_turn
        fail_turn(db, reservation)
        raise HTTPException(409, '档案已修改，请重新加载当前命盘的报告。')
    return {'state': 'reserved', 'reservation': reservation, 'paipan': prepared['payload']['paipan'],
            'kb_index_dir': prepared['payload']['kb_index_dir'], 'kb_topk': prepared['payload']['kb_topk']}


def validate_completion(db, conversation, reservation):
    """Validate before charge commits; replaced workers cannot save or consume."""
    # Completion locks conversation -> quota -> profile -> personal -> turn.
    # Common retry commits its conversation/turn locks before binding here.
    profile = db.scalar(select(UserProfile).where(UserProfile.id == reservation['profile_id'],
                                                 UserProfile.user_id == conversation.user_id)
                        .with_for_update().execution_options(populate_existing=True))
    job = db.scalar(select(PersonalReportRequest).where(PersonalReportRequest.profile_id == reservation['profile_id'])
                    .with_for_update().execution_options(populate_existing=True))
    if (not profile or not job or job.user_id != conversation.user_id or job.token != reservation['token']
            or job.state != 'pending' or job.lease_until <= datetime.utcnow() or job.conversation_id != conversation.id
            or chart_hash(profile.bazi_chart) != reservation['chart_hash']
            or job.chart_hash != reservation['chart_hash']):
        raise HTTPException(409, '报告生成状态或命盘已发生变化，请重新加载查看最新报告。')
    return job


def mark_failed(db, reservation):
    if reservation.get('request_key'):
        from app.services.chat_turn_request import mark_failed as fail_turn
        # Release common state first, then the profile guard in a separate short
        # transaction. Never hold a turn lock while acquiring a profile guard.
        fail_turn(db, reservation)
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
        result = start_chat(prepared['paipan'], prepared.get('kb_index_dir'), prepared.get('kb_topk', 0), request, user_id=user_id, db=db,
                            profile_id=reservation['profile_id'], report_reservation=reservation, turn_reservation=reservation)
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
