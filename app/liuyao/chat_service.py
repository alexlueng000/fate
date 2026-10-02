"""
六爻多轮对话业务逻辑。

复用 app.chat 下的：
- store.set_conv / get_conv / append_history
- deepseek_client.call_deepseek_stream / call_deepseek
- sse.should_stream / sse_pack / sse_response
- markdown_utils.normalize_markdown
- utils.IncrementalNormalizer / scrub_br_block / collapse_double_newlines / third_sub
- rag.retrieve_kb (kb_type="liuyao")
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.chat import utils
from app.chat.deepseek_client import (
    DeepSeekEmptyResponseError,
    call_deepseek,
    call_deepseek_stream,
    set_caller,
)
from app.chat.markdown_utils import normalize_markdown
from app.chat.rag import retrieve_kb, resolve_index_dir
from app.chat.consultation import bounded_history, consultation_context
from app.chat.sse import should_stream, sse_pack, sse_response
from app.chat.store import append_history, get_conv, set_conv
from app.models.chat import Conversation, Message
from app.models.liuyao import LiuyaoHexagram
from app.services.completed_reply import save_completed_exchange

from .prompts import (
    build_opening_user_message,
    build_system_prompt,
)

logger = get_logger("liuyao.chat")


def _append_completed_history(cid, question, reply):
    try:
        append_history(cid, "user", question)
        append_history(cid, "assistant", reply)
    except Exception as error:
        # The durable reply is already saved/charged. Cache failure must not
        # tell the client to retry and accidentally charge another reply.
        logger.warning("liuyao_cache_update_failed", cid=cid, error=str(error))
        from app.chat.store import delete_conv
        try:
            delete_conv(cid)
        except Exception:
            pass


def _stream_completed_reply(messages, cid, db_conv_id, user_id, question, t0, caller_tag):
    def gen():
        normalizer = utils.IncrementalNormalizer(normalize_interval=50)
        received_text = False
        try:
            yield sse_pack({"meta": {"conversation_id": cid}})
            set_caller(caller_tag)
            try:
                for delta in call_deepseek_stream(messages, thinking=False, require_complete=True):
                    if not delta:
                        continue
                    received_text = True
                    clean = normalizer.append(delta)
                    if clean:
                        yield sse_pack({"text": clean, "replace": True})
                final = normalizer.finalize()
            except DeepSeekEmptyResponseError:
                # A reasoning-only empty stream may use one complete fallback.
                # A truncated visible answer must fail rather than be replayed.
                if received_text:
                    raise
                final = _fallback_non_stream_reply(messages, caller_tag)
            if not final.strip():
                raise ValueError("empty completed reply")
            from app.db import SessionLocal
            with SessionLocal() as session:
                message_id = save_completed_exchange(session, db_conv_id, user_id, question, final,
                    latency_ms=int(utils.now_ms() - t0), quota_type="liuyao_chat")
            _append_completed_history(cid, question, final)
            yield sse_pack({"text": final, "replace": True})
            yield sse_pack({"meta": {"message_id": message_id}})
            yield sse_pack("[DONE]")
        except Exception as error:
            logger.error("liuyao_reply_failed", cid=cid, error=str(error))
            quota_error = isinstance(error, HTTPException) and error.status_code == 429
            yield sse_pack({"error": error.detail if quota_error else "本次解读未能确认完成或保存，请刷新记录后再试。",
                            "status": 429 if quota_error else 500})
    return sse_response(gen)


def _fallback_non_stream_reply(messages: List[dict], caller_tag: str) -> str:
    """Use non-streaming DeepSeek once when the streaming response contains no text."""
    set_caller(f"{caller_tag}_fallback")
    reply = _post_process(call_deepseek(messages, thinking=False, require_complete=True))
    if not reply.strip():
        raise RuntimeError(f"empty_{caller_tag}_fallback_reply")
    return reply


def _parse_db_conversation_id(conversation_id: str) -> Optional[int]:
    """Extract the numeric DB conversation id from current and legacy ids."""
    raw_id = conversation_id
    for prefix in ("liuyao_conv_", "conv_"):
        if raw_id.startswith(prefix):
            raw_id = raw_id.removeprefix(prefix)
            break
    return int(raw_id) if raw_id.isdigit() else None


def _create_db_conversation(
    db: Session,
    user_id: int,
    hexagram: LiuyaoHexagram,
    task_context: Optional[Dict[str, Any]] = None,
) -> int:
    """为这次解卦新建一条对话记录。"""
    title = f"六爻｜{(hexagram.question or '')[:24]}"
    conv = Conversation(
        user_id=user_id,
        title=title,
        liuyao_hexagram_id=hexagram.id,
        task_context=task_context,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv.id


def _build_messages(
    composed_system: str,
    history: List[dict],
    extra_user: Optional[str] = None,
    recent_n: int = 10,
) -> List[dict]:
    msgs: List[dict] = [{"role": "system", "content": composed_system}]
    msgs.extend(bounded_history(history, recent_n))
    if extra_user is not None:
        msgs.append({"role": "user", "content": extra_user})
    return msgs


def _post_process(reply_raw: str) -> str:
    reply = normalize_markdown(reply_raw).strip()
    reply = utils.scrub_br_block(reply)
    reply = utils.collapse_double_newlines(reply)
    reply = utils.third_sub(reply)
    return reply


def _print_deepseek_payload(tag: str, messages: List[dict]) -> None:
    """
    把发往 DeepSeek 的完整 messages 直接打印到控制台，方便调试。
    生产环境可通过环境变量 LIUYAO_PRINT_PAYLOAD=0 关闭。
    """
    import os
    if os.getenv("LIUYAO_PRINT_PAYLOAD", "0") == "0":
        return
    sep = "=" * 88
    total = sum(len(m.get("content", "")) for m in messages)
    print(f"\n{sep}", flush=True)
    print(f"[deepseek][liuyao:{tag}] {len(messages)} messages, total {total} chars", flush=True)
    for i, m in enumerate(messages):
        role = m.get("role", "?")
        content = m.get("content", "") or ""
        print(f"\n── #{i} role={role} (len={len(content)}) ──", flush=True)
        print(content, flush=True)
    print(f"{sep}\n", flush=True)


def start_liuyao_chat(
    hexagram: LiuyaoHexagram,
    request: Request,
    user_id: int,
    db: Session,
    task_context: Optional[Dict[str, Any]] = None,
):
    """
    开始六爻对话：
      1. 检索六爻 KB
      2. 构建 system prompt + 开场用户消息
      3. 创建 DB Conversation 记录
      4. 流式调用 DeepSeek，结束后落库
    """
    t0 = utils.now_ms()

    kb_query = " ".join(filter(None, [
        hexagram.main_gua, hexagram.change_gua, hexagram.question
    ]))
    try:
        kb_passages = retrieve_kb(query=kb_query, kb_type="liuyao", k=5)
    except Exception as e:
        logger.warning("liuyao_kb_retrieve_failed", error=str(e))
        kb_passages = []

    # 优先读 admin 后台维护的 prompt；为空时 build_system_prompt 内部回退到默认值
    base_prompt = utils.load_liuyao_system_prompt_from_db()
    system_prompt = build_system_prompt(hexagram, kb_passages, base_prompt=base_prompt)
    opening_user_msg = build_opening_user_message(hexagram)

    db_conv_id = _create_db_conversation(db, user_id, hexagram, task_context=task_context)
    cid = f"liuyao_conv_{db_conv_id}"

    set_conv(cid, {
        "pinned": system_prompt,
        "history": [],
        "user_id": user_id,
        "db_conv_id": db_conv_id,
        "liuyao_hexagram_id": hexagram.id,
        "kind": "liuyao",
        "task_context": task_context,
    })

    messages = _build_messages(system_prompt, [], extra_user=opening_user_msg)
    messages[1:1] = consultation_context(db, task_context, [])
    _print_deepseek_payload("start", messages)

    if should_stream(request):
        return _stream_completed_reply(messages, cid, db_conv_id, user_id, opening_user_msg, t0, "liuyao_chat_start")

    # 一次性
    set_caller("liuyao_chat_start")
    reply = _post_process(call_deepseek(messages, thinking=False, require_complete=True))
    if not reply.strip():
        raise ValueError("AI 服务返回为空，请重试")
    latency = int(utils.now_ms() - t0)
    save_completed_exchange(db, db_conv_id, user_id, opening_user_msg, reply,
                            latency_ms=latency, quota_type="liuyao_chat")
    _append_completed_history(cid, opening_user_msg, reply)
    return cid, reply


def _send_streaming_message(
    conversation_id: str,
    user_message: str,
    request: Request,
    user_id: int,
    db: Session,
    *,
    display_user_message: Optional[str] = None,
    caller_tag: str = "liuyao_chat_send",
):
    """
    内部统一的"发一条用户消息→流式生成→落库"逻辑。

    display_user_message: 写入 history / DB 的 user 消息内容（默认与 user_message 相同）。
                         快捷按钮场景下，UI 显示的是"人物画像分析"等短标签，
                         但实际让 AI 看到的是完整 prompt。
    """
    conv = get_conv(conversation_id)

    # 服务重启后 in-memory 丢失，尝试从 DB 恢复
    if not conv:
        try:
            db_conv_id_int = _parse_db_conversation_id(conversation_id)
            if db_conv_id_int:
                from app.models.chat import Conversation as ConvModel, Message as MsgModel
                db_conv = db.get(ConvModel, db_conv_id_int)
                if db_conv and db_conv.user_id == user_id and db_conv.liuyao_hexagram_id:
                    from app.models.liuyao import LiuyaoHexagram
                    hexagram = db.get(LiuyaoHexagram, db_conv.liuyao_hexagram_id)
                    if hexagram:
                        base_prompt = utils.load_liuyao_system_prompt_from_db()
                        system_prompt = build_system_prompt(hexagram, [], base_prompt=base_prompt)
                        db_msgs = (
                            db.query(MsgModel)
                            .filter_by(conversation_id=db_conv_id_int)
                            .order_by(MsgModel.id)
                            .all()
                        )
                        history = [
                            {"role": m.role, "content": m.content}
                            for m in db_msgs
                            if m.role in ("user", "assistant")
                        ]
                        set_conv(conversation_id, {
                            "pinned": system_prompt,
                            "history": history,
                            "user_id": user_id,
                            "db_conv_id": db_conv_id_int,
                            "liuyao_hexagram_id": hexagram.id,
                            "kind": "liuyao",
                            "task_context": db_conv.task_context,
                        })
                        conv = get_conv(conversation_id)
                        logger.info("liuyao_conversation_recovered", conversation_id=conversation_id, msg_count=len(history))
        except Exception as e:
            logger.error("liuyao_conversation_recovery_failed", error=str(e), conversation_id=conversation_id)

    if not conv:
        raise ValueError("会话不存在，请先调用 /liuyao/{id}/chat/start")

    if conv.get("kind") != "liuyao":
        raise ValueError("会话类型不匹配")

    conv_user_id = conv.get("user_id")
    if conv_user_id and conv_user_id != user_id:
        raise ValueError("无权访问此会话")

    db_conv_id = conv.get("db_conv_id")
    from app.models.chat import Conversation, Message
    saved = db.get(Conversation, db_conv_id) if db_conv_id else None
    if not saved or saved.user_id != user_id or not saved.liuyao_hexagram_id:
        raise ValueError("会话不存在，请先调用 /liuyao/{id}/chat/start")
    conv = dict(conv)
    conv["task_context"] = saved.task_context
    conv["history"] = [
        {"role": row.role, "content": row.content}
        for row in db.query(Message).filter_by(conversation_id=db_conv_id)
        .order_by(Message.id).all() if row.role in ("user", "assistant")
    ]
    history = conv.get("history") or []
    composed_system = conv.get("pinned") or ""

    persisted_user_msg = display_user_message or user_message

    messages = _build_messages(composed_system, history, extra_user=user_message)
    messages[1:1] = consultation_context(db, conv.get("task_context"), history)
    _print_deepseek_payload(caller_tag, messages)

    t0 = utils.now_ms()

    if should_stream(request):
        return _stream_completed_reply(messages, conversation_id, db_conv_id, user_id, persisted_user_msg, t0, caller_tag)

    # 一次性
    set_caller(caller_tag)
    reply = _post_process(call_deepseek(messages, thinking=False, require_complete=True))
    if not reply.strip():
        raise ValueError("AI 服务返回为空，请重试")
    latency = int(utils.now_ms() - t0)
    save_completed_exchange(db, db_conv_id, user_id, persisted_user_msg, reply,
                            latency_ms=latency, quota_type="liuyao_chat")
    _append_completed_history(conversation_id, persisted_user_msg, reply)
    return reply


def send_liuyao_chat(
    conversation_id: str,
    message: str,
    request: Request,
    user_id: int,
    db: Session,
):
    """续聊：用户输入消息，流式返回。"""
    return _send_streaming_message(
        conversation_id=conversation_id,
        user_message=message,
        request=request,
        user_id=user_id,
        db=db,
        caller_tag="liuyao_chat_send",
    )


def quick_liuyao_chat(
    conversation_id: str,
    label: str,
    prompt: str,
    request: Request,
    user_id: int,
    db: Session,
):
    """快捷按钮：管理后台配置的 label + prompt 直接转发到流式对话。"""
    return _send_streaming_message(
        conversation_id=conversation_id,
        user_message=prompt,
        display_user_message=label,
        request=request,
        user_id=user_id,
        db=db,
        caller_tag="liuyao_chat_quick",
    )


def regenerate_liuyao_chat(
    conversation_id: str,
    user_id: int,
    db: Session,
    expected_message_id=None,
    expected_hexagram_id=None,
):
    """
    重新生成上一条 assistant 回复（一次性，非流式）。
    复用现有 history 的最后一条 user 消息。
    """
    from app.services.conversation_actions import owned_conversation, saved_messages, append_regeneration
    from app.models.liuyao import LiuyaoHexagram
    saved = owned_conversation(db, conversation_id, user_id, 'liuyao')
    if expected_hexagram_id is not None and saved.liuyao_hexagram_id != expected_hexagram_id:
        raise ValueError('会话不存在')
    rows = saved_messages(db, saved.id)
    if not rows or rows[-1].role != 'assistant':
        raise ValueError('还没有已保存的完整回复，不能重新解读。')
    target_id = rows[-1].id
    if expected_message_id is not None and target_id != expected_message_id:
        raise HTTPException(409, '会话已有新的回复，请重新加载后再重新解读。')
    hexagram = db.get(LiuyaoHexagram, saved.liuyao_hexagram_id)
    if not hexagram or hexagram.user_id != user_id:
        raise ValueError('会话不存在')
    history = bounded_history([{'role': row.role, 'content': row.content} for row in rows], len(rows))
    if not history:
        raise ValueError("会话尚无历史，无法重新生成")

    # 找到最后一条 user 消息及其前面的 assistant 消息
    last_user_idx = None
    for i in range(len(history) - 1, -1, -1):
        if history[i].get("role") == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        raise ValueError("未找到上一条用户消息")

    truncated = history[: last_user_idx + 1]
    base_prompt = utils.load_liuyao_system_prompt_from_db()
    try:
        kb_passages = retrieve_kb(history[last_user_idx]['content'], resolve_index_dir('liuyao'), k=3)
    except Exception:
        kb_passages = []
    composed_system = build_system_prompt(hexagram, kb_passages, base_prompt=base_prompt)
    messages = [{"role": "system", "content": composed_system}, *truncated]
    messages[1:1] = consultation_context(db, saved.task_context, truncated)
    _print_deepseek_payload("regenerate", messages)

    set_caller("liuyao_chat_regenerate")
    reply = _post_process(call_deepseek(messages, thinking=False, require_complete=True))

    message_id = append_regeneration(db, saved.id, user_id, target_id, reply, 'liuyao')
    from app.chat.store import delete_conv
    try:
        delete_conv(conversation_id)
    except Exception:
        logger.warning('regeneration_cache_invalidation_failed', conversation_id=conversation_id)
    return {'reply': reply, 'message_id': message_id}
