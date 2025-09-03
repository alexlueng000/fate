from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.chat import Conversation, Message
from app.schemas.chat import (
    ConversationCreateReq, ConversationRenameReq, ConversationDeleteReq,
    ConversationItem, ConversationListResp, HistoryResp, MessageItem
)
from app.deps import get_current_user_or_401

router = APIRouter(prefix="/chat", tags=["chat-basic"])


@router.get("/conversations", response_model=ConversationListResp)
def list_conversations(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    q = (
        select(Conversation.id, Conversation.title, Conversation.updated_at)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    rows = db.execute(q).all()
    items = [ConversationItem(id=r.id, title=r.title, updated_at=r.updated_at) for r in rows]
    return ConversationListResp(items=items)


@router.post("/conversations", response_model=ConversationItem, status_code=status.HTTP_201_CREATED)
def create_conversation(
    req: ConversationCreateReq,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    c = Conversation(user_id=user_id, title=(req.title or "未命名会话"))
    db.add(c)
    db.commit()
    db.refresh(c)
    return ConversationItem(id=c.id, title=c.title, updated_at=c.updated_at)


@router.post("/conversations/rename", status_code=status.HTTP_204_NO_CONTENT)
def rename_conversation(
    req: ConversationRenameReq,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    c = db.get(Conversation, req.conversation_id)
    if not c or c.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    c.title = req.title.strip() or "未命名会话"
    db.add(c)
    db.commit()
    return


@router.post("/conversations/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    req: ConversationDeleteReq,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    c = db.get(Conversation, req.conversation_id)
    if not c or c.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(c)
    db.commit()
    return


@router.get("/history", response_model=HistoryResp)
def get_history(
    conversation_id: int = Query(..., description="会话ID"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    # 权限校验
    c = db.get(Conversation, conversation_id)
    if not c or c.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 分页：按时间（id）升序
    total = db.scalar(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
    ) or 0

    offset = (page - 1) * size
    q = (
        select(
            Message.id, Message.role, Message.content,
            Message.prompt_tokens, Message.completion_tokens,
            Message.latency_ms, Message.created_at
        )
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
        .offset(offset)
        .limit(size)
    )
    rows = db.execute(q).all()
    items = [
        MessageItem(
            id=r.id,
            role=r.role,
            content=r.content,
            prompt_tokens=r.prompt_tokens,
            completion_tokens=r.completion_tokens,
            latency_ms=r.latency_ms,
            created_at=r.created_at,
        )
        for r in rows
    ]

    return HistoryResp(
        conversation_id=conversation_id,
        page=page,
        size=size,
        total=total,
        items=items,
    )
