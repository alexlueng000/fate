# app/chat/router.py
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from app.schemas.chat import (
    ChatStartReq, ChatStartResp,
    ChatSendReq, ChatSendResp,
    ChatRegenerateReq, ChatClearReq, ChatOkResp
)
from app.chat.service import start_chat, send_chat, regenerate, clear

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/start", response_model=ChatStartResp)
def chat_start(req: ChatStartReq, request: Request, db: Session = Depends(get_db)):
    """
    开始会话：支持 SSE（根据 Accept 或 ?stream=1）
    """
    print("chat_start", req)
    result = start_chat(
        paipan=req.paipan.model_dump(),
        kb_index_dir=req.kb_index_dir,
        kb_topk=req.kb_topk,
        request=request,
    )
    # 流式：直接返回 StreamingResponse
    from fastapi.responses import StreamingResponse
    if isinstance(result, StreamingResponse):
        return result  # type: ignore[return-value]
    # 一次性：返回结构化 JSON
    cid, reply = result
    print("chat_start", cid, reply)
    return ChatStartResp(conversation_id=cid, reply=reply)

@router.post("", response_model=ChatSendResp)
def chat_send(req: ChatSendReq, request: Request, db: Session = Depends(get_db)):
    """
    续聊：支持 SSE（根据 Accept 或 ?stream=1）
    """
    try:
        result = send_chat(req.conversation_id, req.message, request)
    except ValueError as e:
        raise HTTPException(status_code=404 if "会话不存在" in str(e) else 400, detail=str(e))

    from fastapi.responses import StreamingResponse
    if isinstance(result, StreamingResponse):
        return result  # type: ignore[return-value]

    return ChatSendResp(conversation_id=req.conversation_id, reply=result)

@router.post("/regenerate", response_model=ChatSendResp)
def chat_regenerate(req: ChatRegenerateReq, db: Session = Depends(get_db)):
    """
    重新生成上一条 Assistant 回复（一次性）
    """
    try:
        reply = regenerate(req.conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=404 if "会话不存在" in str(e) else 400, detail=str(e))
    return ChatSendResp(conversation_id=req.conversation_id, reply=reply)


@router.post("/clear", response_model=ChatOkResp)
def chat_clear(req: ChatClearReq, db: Session = Depends(get_db)):
    """
    清空指定会话的历史记录
    """
    try:
        clear(req.conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=404 if "会话不存在" in str(e) else 400, detail=str(e))
    return ChatOkResp(ok=True, conversation_id=req.conversation_id)