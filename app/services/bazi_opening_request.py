"""Protect the legacy /chat opening without substituting a welcome message.

The source key is resolved on the server. Tabs without a local request key can
locate the same first report; changed charts or explicit facts remain separate.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.bazi_opening_request import BaziOpeningRequest
from app.models.chat import Conversation, Message
from app.models.chat_turn_request import ChatTurnRequest
from app.models.guest_analysis import GuestAnalysis
from app.models.profile import UserProfile
from app.services.chat_turn_request import LEASE_MINUTES, execute_prepared_turn, request_status, reserve_turn
from app.services.conversation_actions import numeric_id
from app.services.conversation_report import require_personal_report
from app.services.quota import QuotaService


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _chart(payload):
    chart = payload.get('mingpan', payload) if isinstance(payload, dict) else None
    if not isinstance(chart, dict) or not all(chart.get(field) for field in ('gender', 'four_pillars', 'dayun')):
        raise HTTPException(400, '命盘数据不完整，请先完善档案或重新排盘。')
    return chart


def _source(db, user_id, req, *, lock=False):
    query = select(UserProfile).where(UserProfile.user_id == user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    profile = db.scalar(query)
    profile_id = profile.id if profile else None
    if req.guest_analysis_public_id:
        query = select(GuestAnalysis).where(GuestAnalysis.public_id == req.guest_analysis_public_id,
                                            GuestAnalysis.user_id == user_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        analysis = db.scalar(query)
        if not analysis:
            raise HTTPException(404, '游客分析不存在或尚未保存到当前账户')
        if analysis.status != 'succeeded':
            raise HTTPException(400, '游客分析尚未生成完成')
        if analysis.expires_at and analysis.expires_at < datetime.utcnow():
            raise HTTPException(400, '游客分析已过期')
        chart = _chart(analysis.bazi_result)
        if not profile or profile.bazi_chart != analysis.bazi_result:
            profile_id = None
        identity = {'guest_analysis_public_id': analysis.public_id}
    else:
        if not profile:
            raise HTTPException(400, '请先完善个人档案')
        chart = _chart(profile.bazi_chart)
        identity = {'profile_id': profile_id}
    source = {**identity, 'paipan': chart, 'task_context': req.task_context or None}
    # Model settings do not create a second first report for the same source.
    payload = {**source, 'kb_index_dir': req.kb_index_dir, 'kb_topk': req.kb_topk}
    return _digest(source), payload, profile_id


def _legacy_reply(db, user_id, payload, profile_id):
    # A guest's old unlinked conversation cannot prove its public source ID.
    if not profile_id or payload.get('guest_analysis_public_id'):
        return {'state': 'idle'}
    conversations = db.scalars(select(Conversation).where(Conversation.user_id == user_id,
        Conversation.profile_id == profile_id, Conversation.liuyao_hexagram_id.is_(None)).order_by(Conversation.id))
    for conversation in conversations:
        snapshot = conversation.bazi_chart_snapshot or {}
        if snapshot.get('mingpan', snapshot) != payload['paipan'] or (conversation.task_context or None) != payload['task_context']:
            continue
        messages = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id,
            Message.user_id == user_id, Message.role.in_(['user', 'assistant'])).order_by(Message.id)))
        # Ordinary follow-ups and later seven-chapter answers are not openings.
        if len(messages) < 2 or messages[0].role != 'user' or not messages[0].content.startswith('我的命盘信息如下') or messages[1].role != 'assistant':
            continue
        try:
            require_personal_report(messages[1].content)
        except ValueError:
            continue
        message = messages[1]
        return {'state': 'succeeded', 'conversation_id': f'bazi_conv_{conversation.id}',
                'reply': message.content, 'message_id': message.id}
    return {'state': 'idle'}


def _mapping_details(db, user_id, mapping):
    conversation = db.get(Conversation, mapping.conversation_id)
    job = db.get(ChatTurnRequest, (user_id, mapping.request_key))
    payload = mapping.request_payload
    source = {key: value for key, value in payload.items() if key not in ('kb_index_dir', 'kb_topk')} if isinstance(payload, dict) else None
    if (mapping.user_id != user_id or not conversation or conversation.user_id != user_id
            or conversation.liuyao_hexagram_id or not job or job.kind != 'bazi'
            or job.conversation_id != conversation.id or not isinstance(payload, dict)
            or _digest(source) != mapping.source_hash
            or job.payload_hash != _digest({'opening_source_hash': mapping.source_hash})
            or conversation.bazi_chart_snapshot != payload.get('paipan')
            or (conversation.task_context or None) != payload.get('task_context')):
        raise HTTPException(409, '首次解读记录无法确认，请从解读记录检查原对话。')
    return conversation, payload


def opening_status(db, user_id, req=None, *, conversation_id=None):
    if conversation_id is not None:
        cid = numeric_id(conversation_id, 'bazi')
        conversation = db.get(Conversation, cid)
        if not conversation or conversation.user_id != user_id or conversation.liuyao_hexagram_id:
            raise HTTPException(404, '会话不存在')
        mapping = db.scalar(select(BaziOpeningRequest).where(BaziOpeningRequest.user_id == user_id,
                                                            BaziOpeningRequest.conversation_id == cid))
        if not mapping:
            return {'state': 'idle', 'conversation_id': f'bazi_conv_{cid}'}
    else:
        source_hash, payload, profile_id = _source(db, user_id, req)
        mapping = db.get(BaziOpeningRequest, (user_id, source_hash))
        if not mapping:
            return {**_legacy_reply(db, user_id, payload, profile_id),
                    'paipan': payload['paipan'], 'task_context': payload['task_context'], 'source_hash': source_hash}
    _, payload = _mapping_details(db, user_id, mapping)
    return {**request_status(db, user_id, mapping.request_key),
            'paipan': payload['paipan'], 'task_context': payload['task_context'], 'source_hash': mapping.source_hash}


def _existing(db, user_id, mapping):
    conversation, payload = _mapping_details(db, user_id, mapping)
    job = db.get(ChatTurnRequest, (user_id, mapping.request_key))
    if job.state != 'succeeded' and db.scalar(select(Message.id).where(Message.conversation_id == conversation.id).limit(1)):
        raise HTTPException(409, '原会话已有新的内容，请从解读记录查看，不再重新生成首次报告。')
    cid, key, source_hash, profile_id = conversation.id, mapping.request_key, mapping.source_hash, conversation.profile_id
    # Release source/quota locks before reserving an existing conversation.
    # Existing reservations and completion use conversation -> quota -> request.
    db.commit()
    prepared = reserve_turn(db, user_id, f'bazi_conv_{cid}', 'bazi', key, {'opening_source_hash': source_hash})
    return {**prepared, 'conversation_id': f'bazi_conv_{cid}', 'request_key': key,
            'payload': payload, 'profile_id': profile_id}


def reserve_opening(db, user_id, req=None, *, conversation_id=None):
    source_hash = None
    try:
        if conversation_id is not None:
            cid = numeric_id(conversation_id, 'bazi')
            mapping = db.scalar(select(BaziOpeningRequest).where(BaziOpeningRequest.user_id == user_id,
                                                                BaziOpeningRequest.conversation_id == cid))
            if not mapping:
                raise HTTPException(404, '首次解读请求不存在')
            return _existing(db, user_id, mapping)
        allowed, message, _ = QuotaService.check_available(db, user_id, 'chat', commit=False)
        source_hash, payload, profile_id = _source(db, user_id, req, lock=True)
        mapping = db.get(BaziOpeningRequest, (user_id, source_hash))
        if mapping:
            return _existing(db, user_id, mapping)
        legacy = _legacy_reply(db, user_id, payload, profile_id)
        if legacy['state'] == 'succeeded':
            db.commit()
            return legacy
        if not allowed:
            raise HTTPException(429, message)
        conversation = Conversation(user_id=user_id, profile_id=profile_id, title='八字解读',
            bazi_chart_snapshot=payload['paipan'], task_context=payload['task_context'])
        db.add(conversation); db.flush()
        key, token, now = uuid.uuid4().hex, uuid.uuid4().hex, datetime.utcnow()
        turn_payload = {'opening_source_hash': source_hash}
        db.add(ChatTurnRequest(user_id=user_id, request_key=key, conversation_id=conversation.id,
            active_conversation_id=conversation.id, kind='bazi', payload_hash=_digest(turn_payload), request_payload=turn_payload,
            state='pending', token=token, baseline_message_id=0, lease_until=now + timedelta(minutes=LEASE_MINUTES), updated_at=now))
        db.add(BaziOpeningRequest(user_id=user_id, source_hash=source_hash, request_key=key,
            conversation_id=conversation.id, request_payload=payload))
        reservation = {'user_id': user_id, 'request_key': key, 'token': token, 'conversation_id': conversation.id}
        cid = f'bazi_conv_{conversation.id}'
        db.commit()
        return {'state': 'reserved', 'conversation_id': cid, 'request_key': key, 'reservation': reservation,
                'payload': payload, 'profile_id': profile_id}
    except IntegrityError:
        db.rollback()
        mapping = db.get(BaziOpeningRequest, (user_id, source_hash)) if source_hash else None
        if mapping:
            return _existing(db, user_id, mapping)
        raise
    except Exception:
        db.rollback(); raise


def generate_opening(db, user_id, req, request, *, conversation_id=None):
    from app.chat.service import start_chat
    try:
        prepared = reserve_opening(db, user_id, req, conversation_id=conversation_id)
    except SQLAlchemyError as error:
        raise HTTPException(503, '首次解读保存服务暂不可用，请稍后重试。') from error
    cid = prepared['conversation_id']
    def dispatch(reservation):
        payload = prepared['payload']
        return start_chat(payload['paipan'], payload['kb_index_dir'], payload['kb_topk'], request,
            user_id=user_id, db=db, profile_id=prepared['profile_id'], task_context=payload['task_context'], turn_reservation=reservation)
    result = execute_prepared_turn(db, prepared, prepared.get('request_key'), request, dispatch)
    return (cid, result) if isinstance(result, str) else result
