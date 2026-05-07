# app/chat/router.py
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..db import get_db, get_db_tx
from ..deps import get_current_user_optional
from ..models import User
from ..models.profile import UserProfile
from ..services.quota import QuotaService
from app.schemas.chat import (
    ChatStartReq, ChatStartResp, ChatInitResp,
    ChatSendReq, ChatSendResp,
    ChatRegenerateReq, ChatClearReq, ChatOkResp,
    ChatSimplifyReq,
)
from app.chat.service import start_chat, send_chat, regenerate, clear, simplify_message, init_chat
from app.core.logging import get_logger
import json

logger = get_logger("chat.router")
router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/init", response_model=ChatInitResp)
def chat_init(
    db: Session = Depends(get_db_tx),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    初始化会话（不生成 AI 开场白），仅返回 conversation_id。
    前端展示静态开场白，用户发消息后直接调 /chat 接口。
    不消耗配额——配额仅在用户实际提问（/chat/start 或 /chat）时扣减。
    """
    user_id = current_user.id if current_user else None
    cid = init_chat(user_id=user_id, db=db)
    return ChatInitResp(conversation_id=cid)

@router.post("/start", response_model=ChatStartResp)
def chat_start(
    req: ChatStartReq,
    request: Request,
    db: Session = Depends(get_db_tx),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    开始会话：支持 SSE（根据 Accept 或 ?stream=1）
    - 已登录用户会检查配额并记录使用
    - 未登录用户暂时允许使用（内测阶段）
    - 已登录用户必须先建档，从档案读取命盘数据
    """
    user_id = current_user.id if current_user else None
    profile_id = None
    paipan_data = req.paipan.model_dump() if req.paipan else {}

    # 已登录用户：从档案读取命盘
    if user_id:
        profile = db.query(UserProfile).filter_by(user_id=user_id).first()
        if not profile:
            raise HTTPException(status_code=400, detail="请先完善个人档案")

        profile_id = profile.id
        # 解包 mingpan 层（数据库中保存的格式是 {"mingpan": {...}}）
        bazi_chart = profile.bazi_chart
        paipan_data = bazi_chart.get("mingpan", bazi_chart) if isinstance(bazi_chart, dict) else bazi_chart
        logger.info("chat_start_with_profile", user_id=user_id, profile_id=profile_id)

        # 配额检查
        allowed, msg, remaining = QuotaService.check_and_consume(db, user_id, "chat")
        if not allowed:
            raise HTTPException(status_code=429, detail=f"配额已用完：{msg}")
        logger.info("quota_consumed", user_id=user_id, remaining=remaining)
    else:
        # 未登录用户：使用请求中的临时命盘
        logger.info("chat_start_anonymous", paipan=paipan_data)

    result = start_chat(
        paipan=paipan_data,
        kb_index_dir=req.kb_index_dir,
        kb_topk=req.kb_topk,
        request=request,
        user_id=user_id,
        db=db,
        profile_id=profile_id,
    )
    # 流式：直接返回 StreamingResponse
    from fastapi.responses import StreamingResponse
    if isinstance(result, StreamingResponse):
        return result  # type: ignore[return-value]
    # 一次性：返回结构化 JSON
    cid, reply = result
    logger.info("chat_start_completed", conversation_id=cid)
    return ChatStartResp(conversation_id=cid, reply=reply)

@router.post("", response_model=ChatSendResp)
def chat_send(
    req: ChatSendReq,
    request: Request,
    db: Session = Depends(get_db_tx),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    续聊：支持 SSE（根据 Accept 或 ?stream=1）
    - 已登录用户每次提问都消耗 1 次八字配额（与 /chat/start 一致）
    - 未登录用户暂不限额（内测）
    """
    logger.debug("chat_send_request", conversation_id=req.conversation_id, user_id=current_user.id if current_user else None)
    user_id = current_user.id if current_user else None
    if user_id:
        allowed, msg, remaining = QuotaService.check_and_consume(db, user_id, "chat")
        if not allowed:
            raise HTTPException(status_code=429, detail=f"配额已用完：{msg}")
        logger.info("quota_consumed", user_id=user_id, remaining=remaining, endpoint="chat_send")
    try:
        result = send_chat(req.conversation_id, req.message, request, user_id=user_id, db=db)
    except ValueError as e:
        raise HTTPException(status_code=404 if "会话不存在" in str(e) else 400, detail=str(e))

    from fastapi.responses import StreamingResponse
    if isinstance(result, StreamingResponse):
        return result  # type: ignore[return-value]

    return ChatSendResp(conversation_id=req.conversation_id, reply=result)

@router.post("/regenerate", response_model=ChatSendResp)
def chat_regenerate(
    req: ChatRegenerateReq,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    重新生成上一条 Assistant 回复（一次性）
    """
    user_id = current_user.id if current_user else None
    try:
        reply = regenerate(req.conversation_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=404 if "会话不存在" in str(e) else 400, detail=str(e))
    return ChatSendResp(conversation_id=req.conversation_id, reply=reply)


@router.post("/simplify")
def chat_simplify(req: ChatSimplifyReq, request: Request):
    """
    将一条 AI 消息内容转化为白话版，流式返回，不影响会话历史。
    """
    from fastapi.responses import StreamingResponse
    result = simplify_message(req.message_content, request)
    if isinstance(result, StreamingResponse):
        return result  # type: ignore[return-value]
    return result


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
            from app.chat.deepseek_client import call_deepseek_stream, set_caller
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
                kb_passages
            )

            # 保存会话
            from app.chat.store import set_conv
            set_conv(cid, {
                "pinned": composed,
                "history": [],
                "kb_index_dir": os.path.abspath(kb_index_dir or DEFAULT_KB_INDEX),
                "kind": "bazi",
                "paipan": paipan,  # 保存八字信息，用于后续对话
            })

            opening_user_msg = (
                f"我的命盘信息如下：\n"
                f"公历出生日期（真太阳时）：{paipan.get('solar_date', '')}\n"
                f"性别：{paipan['gender']}\n"
                f"八字：\n四柱：\n年柱: {''.join(paipan['four_pillars']['year'])}\n"
                f"月柱: {''.join(paipan['four_pillars']['month'])}\n"
                f"日柱: {''.join(paipan['four_pillars']['day'])}\n"
                f"时柱: {''.join(paipan['four_pillars']['hour'])}\n"
                f"大运：\n" + "\n".join(
                    f"- 起始年龄 {item['age']}，起运年 {item['start_year']}，大运 {''.join(item['pillar'])}"
                    for item in paipan['dayun']
                ) + "\n\n"
                "请基于以上命盘做一份通用且全面的解读，条理清晰，"
                "涵盖性格亮点、适合方向、注意点与三年内重点建议。"
                "结尾提醒：以上内容由传统文化AI生成，仅供娱乐参考。"
            )

            messages = [
                {"role": "system", "content": composed},
                {"role": "user", "content": opening_user_msg}
            ]

            # 流式发送
            set_caller("ws_start")
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
            from app.chat.deepseek_client import call_deepseek_stream, set_caller
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

            # 注入本命八字锚点：避免对话中出现多个八字时混淆
            paipan = conv.get("paipan") or {}
            if paipan and paipan.get("four_pillars"):
                fp = paipan["four_pillars"]
                bazi_anchor = (
                    f"\n\n【本命盘锚点 - 始终以此为准】\n"
                    f"用户本人性别：{paipan.get('gender', '')}\n"
                    f"用户本人八字：年柱 {''.join(fp.get('year', []))}，"
                    f"月柱 {''.join(fp.get('month', []))}，"
                    f"日柱 {''.join(fp.get('day', []))}，"
                    f"时柱 {''.join(fp.get('hour', []))}\n"
                    f"重要规则：\n"
                    f"1. 上述八字为用户的本命盘，是一切分析的基准\n"
                    f"2. 若用户在对话中提到他人八字（如配偶、合盘对象），仅作参考对比\n"
                    f"3. 除非用户明确指定分析对象，否则默认所有问题都是关于用户本命盘\n"
                    f"4. 不要将其他人的八字信息覆盖或替换用户的本命盘"
                )
                composed = composed + bazi_anchor

            recentN = 10
            messages = [{"role": "system", "content": composed}]
            messages.extend(conv["history"][-recentN:])
            messages.append({"role": "user", "content": message})

            # 发送 meta 确认
            await websocket.send_json({"meta": {"conversation_id": conversation_id}})

            # 流式发送
            set_caller("ws_send")
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