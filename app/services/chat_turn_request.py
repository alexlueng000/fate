"""Reserve ordinary turns; replay only durable answers, never regenerate on reads."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.models.chat import Conversation, Message
from app.models.chat_turn_request import ChatTurnRequest
from app.services.conversation_actions import numeric_id
from app.services.quota import QuotaService

LEASE_MINUTES = 10


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise HTTPException(400, '请求编号格式不正确')
    return value


def _last_message(db, cid):
    return db.scalar(select(func.max(Message.id)).where(Message.conversation_id == cid)) or 0


def _status(db, job):
    cid = f'{job.kind}_conv_{job.conversation_id}'
    if job.state == 'succeeded':
        message = db.get(Message, job.message_id)
        if not message or message.user_id != job.user_id or message.conversation_id != job.conversation_id or message.role != 'assistant':
            raise HTTPException(409, '保存记录不完整，请从解读记录检查原对话。')
        return {'state': 'succeeded', 'request_key': job.request_key, 'conversation_id': cid,
                'reply': message.content, 'message_id': message.id}
    return {'state': 'pending' if job.state == 'pending' and job.lease_until > datetime.utcnow() else 'retryable',
            'request_key': job.request_key, 'conversation_id': cid}


def request_status(db, user_id, request_key):
    job = db.get(ChatTurnRequest, (user_id, _key(request_key)))
    if not job:
        raise HTTPException(404, '请求记录不存在')
    conversation = db.get(Conversation, job.conversation_id)
    if not conversation or conversation.user_id != user_id:
        raise HTTPException(404, '请求记录不存在')
    return _status(db, job)


def reserve_turn(db, user_id, raw_cid, kind, request_key, payload):
    key = _key(request_key)
    cid = numeric_id(raw_cid, kind)
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    try:
        # Completion takes the same conversation -> quota -> request order.
        conversation = db.scalar(select(Conversation).where(Conversation.id == cid, Conversation.user_id == user_id)
                                 .with_for_update().execution_options(populate_existing=True))
        if not conversation or bool(conversation.liuyao_hexagram_id) != (kind == 'liuyao'):
            raise HTTPException(404, '会话不存在')
        allowed, message, _ = QuotaService.check_available(db, user_id, 'liuyao_chat' if kind == 'liuyao' else 'chat', commit=False)
        job = db.scalar(select(ChatTurnRequest).where(ChatTurnRequest.user_id == user_id, ChatTurnRequest.request_key == key)
                        .with_for_update().execution_options(populate_existing=True))
        if job and (job.conversation_id != cid or job.kind != kind or job.payload_hash != digest):
            raise HTTPException(409, '请求编号已绑定其他问题，请先恢复原请求。')
        if job and (job.state == 'succeeded' or (job.state == 'pending' and job.lease_until > datetime.utcnow())):
            result = _status(db, job); db.commit(); return result
        now = datetime.utcnow()
        active = db.scalar(select(ChatTurnRequest).where(ChatTurnRequest.active_conversation_id == cid)
                           .with_for_update().execution_options(populate_existing=True))
        if active and active.state == 'pending' and active.lease_until > now:
            raise HTTPException(409, '这个会话还有回复正在生成，请先恢复该请求。')
        if active:
            active.state = 'failed'; active.active_conversation_id = None; active.updated_at = now
            db.flush()
        if not allowed:
            raise HTTPException(429, message)
        baseline = _last_message(db, cid)
        if not job:
            job = ChatTurnRequest(user_id=user_id, request_key=key, conversation_id=cid, kind=kind, payload_hash=digest)
            db.add(job)
        job.state = 'pending'; job.active_conversation_id = cid; job.token = uuid.uuid4().hex
        job.baseline_message_id = baseline; job.message_id = None
        job.lease_until = now + timedelta(minutes=LEASE_MINUTES); job.updated_at = now
        reservation = {'user_id': user_id, 'request_key': key, 'token': job.token, 'conversation_id': cid}
        db.commit()
        return {'state': 'reserved', 'reservation': reservation}
    except IntegrityError:
        db.rollback()
        winner = db.get(ChatTurnRequest, (user_id, key))
        if winner and winner.conversation_id == cid and winner.kind == kind and winner.payload_hash == digest:
            result = _status(db, winner); db.commit(); return result
        active = db.scalar(select(ChatTurnRequest).where(ChatTurnRequest.active_conversation_id == cid))
        if active:
            raise HTTPException(409, '这个会话还有回复正在生成，请先恢复该请求。')
        raise
    except Exception:
        db.rollback(); raise


def validate_completion(db, conversation, reservation):
    job = db.scalar(select(ChatTurnRequest).where(ChatTurnRequest.user_id == conversation.user_id,
                                                 ChatTurnRequest.request_key == reservation['request_key'])
                    .with_for_update().execution_options(populate_existing=True))
    if (not job or job.token != reservation['token'] or job.state != 'pending'
            or job.conversation_id != conversation.id or job.active_conversation_id != conversation.id
            or job.lease_until <= datetime.utcnow() or job.baseline_message_id != _last_message(db, conversation.id)):
        raise HTTPException(409, '请求状态或对话已变化，请先恢复保存结果。')
    return job


def mark_failed(db, reservation):
    try:
        job = db.scalar(select(ChatTurnRequest).where(ChatTurnRequest.user_id == reservation['user_id'],
                                                     ChatTurnRequest.request_key == reservation['request_key'])
                        .with_for_update().execution_options(populate_existing=True))
        if job and job.token == reservation['token'] and job.state == 'pending':
            job.state = 'failed'; job.active_conversation_id = None; job.updated_at = datetime.utcnow()
        db.commit()
    except SQLAlchemyError:
        db.rollback()  # Leave unknown outcomes leased; never free a newer token.


def run_turn(db, user_id, cid, kind, key, payload, request, runner):
    from app.chat.sse import sse_pack, sse_response, should_stream
    try:
        prepared = reserve_turn(db, user_id, cid, kind, key, payload)
    except SQLAlchemyError as error:
        raise HTTPException(503, '请求保存服务暂不可用，请稍后重试。') from error
    if prepared['state'] == 'pending':
        raise HTTPException(409, '这个问题正在生成，请查询请求状态后继续。')
    if prepared['state'] == 'succeeded':
        if not should_stream(request):
            return prepared['reply']
        def replay():
            yield sse_pack({'meta': {'conversation_id': prepared['conversation_id'], 'message_id': prepared['message_id'], 'request_key': key}})
            yield sse_pack({'text': prepared['reply'], 'replace': True})
            yield sse_pack('[DONE]')
        return sse_response(replay)
    reservation = prepared['reservation']
    try:
        result = runner(reservation)
    except Exception:
        mark_failed(db, reservation); raise
    if not isinstance(result, StreamingResponse):
        mark_failed(db, reservation)
        return result
    async def track():
        try:
            async for chunk in result.body_iterator:
                yield chunk
        finally:
            from app.db import SessionLocal
            with SessionLocal() as fresh:
                mark_failed(fresh, reservation)
    return StreamingResponse(track(), headers=dict(result.headers), status_code=result.status_code)
