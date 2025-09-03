from __future__ import annotations
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.models.chat import Conversation, Message


def touch_conversation(db: Session, conversation_id: int) -> None:
    c = db.get(Conversation, conversation_id)
    if c:
        c.updated_at = datetime.now(timezone.utc)
        db.add(c)
        db.commit()


def create_message(
    db: Session,
    *,
    conversation_id: int,
    user_id: int,
    role: str,
    content: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int | None = None,
) -> int:
    msg = Message(
        conversation_id=conversation_id,
        user_id=user_id,
        role=role,
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
    )
    db.add(msg)
    # 顺手更新会话更新时间
    c = db.get(Conversation, conversation_id)
    if c:
        db.add(c)  # onupdate 会生效
    db.commit()
    db.refresh(msg)
    return msg.id
