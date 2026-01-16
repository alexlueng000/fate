# app/chat/router.py
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..db import get_db
from app.schemas.chat import (
    ChatStartReq, ChatStartResp,
    ChatSendReq, ChatSendResp,
    ChatRegenerateReq, ChatClearReq, ChatOkResp
)
from app.chat.service import start_chat, send_chat, regenerate, clear
import json
import logging

logger = logging.getLogger(__name__)
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
    如果 conversation_id 为空但提供了 mingpan，会静默创建新会话
    """
    try:
        result = send_chat(req.conversation_id, req.message, request, req.mingpan)
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


# ===================== WebSocket 端点 =====================

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket 聊天端点，支持流式响应

    接收 JSON 格式消息：
    {
        "action": "start" | "send",
        "conversation_id": "...",  // send 时必填
        "paipan": {...},            // start 时必填
        "message": "...",           // send 时必填
        "kb_index_dir": "",
        "kb_topk": 3
    }

    发送 JSON 格式消息：
    {"meta": {"conversation_id": "conv_xxx"}}  // 首次发送
    {"text": "增量文本", "replace": true}      // 流式文本
    [DONE]                                         // 结束标志
    """
    await websocket.accept()

    try:
        # 接收客户端消息
        raw_data = await websocket.receive_text()
        data = json.loads(raw_data)

        action = data.get("action", "send")
        conversation_id = data.get("conversation_id")
        message = data.get("message", "")
        paipan = data.get("paipan")
        kb_index_dir = data.get("kb_index_dir")
        kb_topk = data.get("kb_topk", 3)

        # 构造流式响应生成器
        if action == "start":
            # 开始新对话
            from app.chat.service import start_chat
            from app.chat.utils import IncrementalNormalizer
            from app.chat.deepseek_client import call_deepseek_stream
            from app.chat.sse import should_stream
            from app.chat import utils
            import uuid

            # 生成 conversation_id
            cid = f"conv_{uuid.uuid4().hex[:8]}"

            # 发送 meta 事件
            await websocket.send_json({"meta": {"conversation_id": cid}})

            # 构建消息（复用 start_chat 逻辑）
            from app.chat.utils import load_system_prompt_from_db, build_full_system_prompt
            from app.chat.rag import retrieve_kb
            import os

            DEFAULT_KB_INDEX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "kb_index"))

            # RAG 检索
            kb_passages = []
            if kb_topk:
                try:
                    kb_passages = retrieve_kb(
                        "开场上下文",
                        os.path.abspath(kb_index_dir or DEFAULT_KB_INDEX),
                        k=min(3, kb_topk)
                    )
                except Exception as e:
                    logger.warning(f"RAG failed: {e}")

            # 构建 system prompt
            base_prompt = load_system_prompt_from_db()
            composed = build_full_system_prompt(
                base_prompt,
                {"four_pillars": paipan["four_pillars"], "dayun": paipan["dayun"], "gender": paipan["gender"]},
                kb_passages
            )

            # 保存会话
            from app.chat.store import set_conv
            set_conv(cid, {
                "pinned": composed,
                "history": [],
                "kb_index_dir": os.path.abspath(kb_index_dir or DEFAULT_KB_INDEX)
            })

            opening_user_msg = (
                "请基于以上命盘做一份通用且全面的解读，条理清晰，"
                "涵盖性格亮点、适合方向、注意点与三年内重点建议。"
                "结尾提醒：以上内容由传统文化AI生成，仅供娱乐参考。"
            )

            messages = [
                {"role": "system", "content": composed},
                {"role": "user", "content": opening_user_msg}
            ]

            # 流式发送
            normalizer = IncrementalNormalizer(normalize_interval=50)
            final_text = ""

            try:
                for delta in call_deepseek_stream(messages):
                    if not delta:
                        continue
                    clean = normalizer.append(delta)
                    if clean:
                        await websocket.send_json({"text": clean, "replace": True})

                # 最终文本
                final_text = normalizer.finalize()
                await websocket.send_json({"text": final_text, "replace": True})

                # 保存历史
                from app.chat.store import append_history
                from app.chat.markdown_utils import normalize_markdown
                from app.chat import utils as chat_utils
                reply = normalize_markdown(final_text).strip()
                reply = chat_utils.scrub_br_block(reply)
                reply = chat_utils.collapse_double_newlines(reply)
                reply = chat_utils.third_sub(reply)
                append_history(cid, "user", opening_user_msg)
                append_history(cid, "assistant", reply)

            except Exception as e:
                await websocket.send_text(f"[ERROR]{str(e)}")
                logger.error(f"WebSocket start_chat error: {e}")

        elif action == "send":
            # 继续对话
            from app.chat.service import send_chat
            from app.chat.utils import IncrementalNormalizer
            from app.chat.deepseek_client import call_deepseek_stream
            from app.chat.store import get_conv, append_history
            from app.chat.markdown_utils import normalize_markdown
            from app.chat import utils as chat_utils
            from app.chat.rag import retrieve_kb
            import os

            # 获取会话
            conv = get_conv(conversation_id)
            if not conv:
                await websocket.send_text("[ERROR]会话不存在，请先使用 action=start")
                return

            # RAG 检索
            kb_dir = conv.get("kb_index_dir")
            kb_passages = []
            if kb_dir and os.path.exists(os.path.join(kb_dir, "chunks.json")):
                try:
                    kb_passages = retrieve_kb(message, kb_dir, k=3)
                except Exception:
                    kb_passages = []

            composed = conv["pinned"]
            if kb_passages:
                kb_block = "\n\n".join(kb_passages)
                composed = f"{composed}\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"

            recentN = 10
            messages = [{"role": "system", "content": composed}]
            messages.extend(conv["history"][-recentN:])
            messages.append({"role": "user", "content": message})

            # 发送 meta 确认
            await websocket.send_json({"meta": {"conversation_id": conversation_id}})

            # 流式发送
            normalizer = IncrementalNormalizer(normalize_interval=50)
            final_text = ""

            try:
                for delta in call_deepseek_stream(messages):
                    if not delta:
                        continue
                    clean = normalizer.append(delta)
                    if clean:
                        await websocket.send_json({"text": clean, "replace": True})

                # 最终文本
                final_text = normalizer.finalize()
                await websocket.send_json({"text": final_text, "replace": True})

                # 保存历史
                reply = normalize_markdown(final_text).strip()
                reply = chat_utils.scrub_br_block(reply)
                reply = chat_utils.collapse_double_newlines(reply)
                reply = chat_utils.third_sub(reply)
                append_history(conversation_id, "user", message)
                append_history(conversation_id, "assistant", reply)

            except Exception as e:
                await websocket.send_text(f"[ERROR]{str(e)}")
                logger.error(f"WebSocket send_chat error: {e}")

        else:
            await websocket.send_text(f"[ERROR]Invalid action: {action}")

        # 发送完成标志
        await websocket.send_text("[DONE]")

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_text(f"[ERROR]{str(e)}")
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass