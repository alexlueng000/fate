"""Owned conversation actions that preserve saved reports and original answers."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.models.chat import Conversation, Message


def numeric_id(raw_id: str, kind: str) -> int:
    prefixes = ('bazi_conv_', 'conv_') if kind == 'bazi' else ('liuyao_conv_', 'conv_')
    for prefix in prefixes:
        if raw_id.startswith(prefix):
            raw_id = raw_id[len(prefix):]
            break
    if not raw_id.isdigit():
        raise ValueError('会话不存在')
    return int(raw_id)


def owned_conversation(db, raw_id: str, user_id: int, kind: str):
    conversation = db.scalar(select(Conversation).where(
        Conversation.id == numeric_id(raw_id, kind), Conversation.user_id == user_id,
    ))
    if not conversation or bool(conversation.liuyao_hexagram_id) != (kind == 'liuyao'):
        raise ValueError('会话不存在')
    return conversation


def saved_messages(db, conversation_id: int):
    return db.scalars(select(Message).where(Message.conversation_id == conversation_id)
                      .order_by(Message.id)).all()


def append_regeneration(db, conversation_id, user_id, expected_message_id, reply, kind):
    """Append a complete alternative answer; legacy regeneration remains free.

    The original message, report and rating stay intact. A competing follow-up
    or regeneration makes this request stale instead of silently replacing it.
    """
    if not reply.strip():
        raise ValueError('AI 服务未返回完整内容，原回答已保留。')
    try:
        conversation = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
        ).with_for_update().execution_options(populate_existing=True))
        if not conversation or bool(conversation.liuyao_hexagram_id) != (kind == 'liuyao'):
            raise ValueError('会话不存在')
        last = db.scalar(select(Message).where(Message.conversation_id == conversation_id)
                         .order_by(Message.id.desc()).limit(1).with_for_update()
                         .execution_options(populate_existing=True))
        if not last or last.role != 'assistant' or last.id != expected_message_id:
            raise HTTPException(409, '会话已有新的回复，请重新加载后再重新解读。')
        assistant = Message(conversation_id=conversation_id, user_id=user_id,
                            role='assistant', content=reply)
        db.add(assistant)
        conversation.updated_at = datetime.utcnow()
        db.flush()
        message_id = assistant.id
        db.commit()
        return message_id
    except Exception:
        db.rollback()
        raise


def fresh_bazi_conversation(db, original):
    """Clear the active context by forking an empty session; never erase reports."""
    try:
        conversation = Conversation(user_id=original.user_id, profile_id=original.profile_id,
                                    title='八字解读', bazi_chart_snapshot=original.bazi_chart_snapshot,
                                    task_context=None)
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id
        db.commit()
        return conversation_id
    except Exception:
        db.rollback()
        raise
