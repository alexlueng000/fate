"""Atomic persistence and legacy quota accounting for a completed AI answer."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.models.chat import Conversation, Message
from app.services.quota import QuotaService
from app.services.conversation_report import require_personal_report


def save_completed_exchange(db, conversation_id, user_id, question, reply, latency_ms=None, *, quota_type="chat", save_profile_report=False, report_reservation=None, turn_reservation=None):
    if not reply.strip():
        raise ValueError("empty completed reply")
    try:
        if save_profile_report:
            require_personal_report(reply)
        conversation = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ).with_for_update().execution_options(populate_existing=True))
        if not conversation:
            raise ValueError("会话不存在")
        actual_type = "liuyao_chat" if conversation.liuyao_hexagram_id else "chat"
        if quota_type != actual_type:
            raise ValueError("会话类型不匹配")
        allowed, message, _ = QuotaService.consume_completed(db, user_id, quota_type)
        if not allowed:
            raise HTTPException(status_code=429, detail=message)
        report_job = None
        if report_reservation:
            if not save_profile_report or quota_type != 'chat':
                raise ValueError('报告生成类型不匹配')
            from app.services.personal_report_request import validate_completion
            report_job = validate_completion(db, conversation, report_reservation)
        turn_job = None
        if turn_reservation:
            from app.services.chat_turn_request import validate_completion
            turn_job = validate_completion(db, conversation, turn_reservation)
        assistant = Message(conversation_id=conversation_id, user_id=user_id,
                            role="assistant", content=reply, latency_ms=latency_ms)
        db.add_all([Message(conversation_id=conversation_id, user_id=user_id,
                            role="user", content=question), assistant])
        if save_profile_report and conversation.profile_id and quota_type == "chat":
            from app.models.profile import UserProfile
            profile = db.scalar(select(UserProfile).where(
                UserProfile.id == conversation.profile_id, UserProfile.user_id == user_id,
            ).with_for_update().execution_options(populate_existing=True))
            snapshot = conversation.bazi_chart_snapshot or {}
            current = profile.bazi_chart if profile else None
            if current and current.get("mingpan", current) == snapshot.get("mingpan", snapshot):
                profile.ai_report = reply
        conversation.updated_at = datetime.utcnow()
        db.flush()
        message_id = assistant.id
        if report_job:
            report_job.state = 'succeeded'; report_job.updated_at = datetime.utcnow()
        if turn_job:
            turn_job.state = 'succeeded'; turn_job.active_conversation_id = None
            turn_job.message_id = message_id; turn_job.updated_at = datetime.utcnow()
        db.commit()
        return message_id
    except Exception:
        db.rollback()
        raise
