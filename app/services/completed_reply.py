"""Atomic persistence and legacy quota accounting for a completed AI answer."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.models.chat import Conversation, Message
from app.services.quota import QuotaService
from app.services.conversation_report import require_personal_report


def save_completed_exchange(db, conversation_id, user_id, question, reply, latency_ms=None, *, quota_type="chat", save_profile_report=False):
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
        db.commit()
        return message_id
    except Exception:
        db.rollback()
        raise
