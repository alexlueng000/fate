"""Bind a hexagram's first generation to the ordinary durable turn protocol."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.chat import Conversation, Message
from app.models.liuyao import LiuyaoHexagram
from app.models.liuyao_opening_request import LiuyaoOpeningRequest
from app.models.chat_turn_request import ChatTurnRequest
from app.services.chat_turn_request import LEASE_MINUTES, request_status, reserve_turn, execute_prepared_turn
from app.services.quota import QuotaService


def _owned_hexagram(db, user_id, hexagram_id, *, lock=False):
    query = select(LiuyaoHexagram).where(LiuyaoHexagram.hexagram_id == hexagram_id, LiuyaoHexagram.user_id == user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    hexagram = db.scalar(query)
    if not hexagram:
        raise HTTPException(404, '卦象不存在')
    return hexagram


def _legacy_reply(db, user_id, hexagram_id):
    # Preserve the earliest saved opening, including reports from before the
    # request tables existed. Reading an archive must never spend quota again.
    message = db.scalar(select(Message).join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id, Conversation.liuyao_hexagram_id == hexagram_id,
               Message.user_id == user_id, Message.role == 'assistant', Message.content != '')
        .order_by(Message.id).limit(1))
    if message:
        return {'state': 'succeeded', 'conversation_id': f'liuyao_conv_{message.conversation_id}',
                'message_id': message.id, 'reply': message.content}
    return {'state': 'idle'}


def opening_status(db, user_id, hexagram_id):
    hexagram = _owned_hexagram(db, user_id, hexagram_id)
    mapping = db.get(LiuyaoOpeningRequest, hexagram.id)
    if not mapping:
        return _legacy_reply(db, user_id, hexagram.id)
    if mapping.user_id != user_id:
        raise HTTPException(404, '请求记录不存在')
    status = request_status(db, user_id, mapping.request_key)
    if status['conversation_id'] != f'liuyao_conv_{mapping.conversation_id}':
        raise HTTPException(409, '首次解读记录不完整，请从解读记录检查原对话。')
    return status


def _payload(hexagram):
    return {'opening_hexagram_id': hexagram.hexagram_id}


def _existing(db, user_id, hexagram, mapping):
    if mapping.user_id != user_id:
        raise HTTPException(404, '请求记录不存在')
    cid, key = mapping.conversation_id, mapping.request_key
    conversation = db.get(Conversation, cid)
    if not conversation or conversation.user_id != user_id or conversation.liuyao_hexagram_id != hexagram.id:
        raise HTTPException(409, '首次解读记录不完整，请从解读记录检查原对话。')
    job = db.get(ChatTurnRequest, (user_id, key))
    if not job or job.conversation_id != cid or job.kind != 'liuyao':
        raise HTTPException(409, '首次解读请求记录不完整，请从解读记录检查原对话。')
    context = conversation.task_context
    payload = _payload(hexagram)
    # Release the hexagram/quota locks before reserving an EXISTING conversation.
    # Completion and reserve_turn lock conversation -> quota -> request. This
    # avoids introducing a reversed lock order for a retried opening.
    db.commit()
    prepared = reserve_turn(db, user_id, f'liuyao_conv_{cid}', 'liuyao', key, payload)
    return {**prepared, 'conversation_id': f'liuyao_conv_{cid}', 'request_key': key, 'task_context': context}


def reserve_opening(db, user_id, hexagram_id, task_context=None):
    try:
        allowed, message, _ = QuotaService.check_available(db, user_id, 'liuyao_chat', commit=False)
        hexagram = _owned_hexagram(db, user_id, hexagram_id, lock=True)
        mapping = db.get(LiuyaoOpeningRequest, hexagram.id)
        if mapping:
            return _existing(db, user_id, hexagram, mapping)
        legacy = _legacy_reply(db, user_id, hexagram.id)
        if legacy['state'] == 'succeeded':
            db.commit()
            return legacy
        if not allowed:
            raise HTTPException(429, message)
        # Only NEW conversations are created under quota -> hexagram locks.
        # The mapping, conversation and active turn slot commit together, so
        # another tab cannot create or reserve a competing first generation.
        conversation = Conversation(user_id=user_id, liuyao_hexagram_id=hexagram.id,
            title=f"六爻｜{(hexagram.question or '')[:24]}", task_context=task_context)
        db.add(conversation); db.flush()
        now = datetime.utcnow()
        key, token = uuid.uuid4().hex, uuid.uuid4().hex
        payload = _payload(hexagram)
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        db.add(ChatTurnRequest(user_id=user_id, request_key=key, conversation_id=conversation.id,
            active_conversation_id=conversation.id, kind='liuyao', payload_hash=digest, state='pending', token=token,
            baseline_message_id=0, lease_until=now + timedelta(minutes=LEASE_MINUTES), updated_at=now))
        db.add(LiuyaoOpeningRequest(hexagram_id=hexagram.id, user_id=user_id, request_key=key, conversation_id=conversation.id))
        reservation = {'user_id': user_id, 'request_key': key, 'token': token, 'conversation_id': conversation.id}
        cid = f'liuyao_conv_{conversation.id}'
        db.commit()
        return {'state': 'reserved', 'reservation': reservation, 'conversation_id': cid,
                'request_key': key, 'task_context': task_context}
    except IntegrityError:
        db.rollback()
        hexagram = _owned_hexagram(db, user_id, hexagram_id)
        mapping = db.get(LiuyaoOpeningRequest, hexagram.id)
        if mapping:
            return _existing(db, user_id, hexagram, mapping)
        raise
    except Exception:
        db.rollback()
        raise


def generate_opening(db, user_id, hexagram_id, task_context, request):
    from app.liuyao.chat_service import start_liuyao_chat
    try:
        prepared = reserve_opening(db, user_id, hexagram_id, task_context)
    except SQLAlchemyError as error:
        raise HTTPException(503, '首次解读保存服务暂不可用，请稍后重试。') from error
    cid = prepared['conversation_id']
    result = execute_prepared_turn(db, prepared, prepared.get('request_key'), request,
        lambda reservation: start_liuyao_chat(_owned_hexagram(db, user_id, hexagram_id), request, user_id, db,
            task_context=prepared['task_context'], turn_reservation=reservation))
    return (cid, result) if isinstance(result, str) else result
