# app/chat/service.py
"""
Main chat service business logic.

This module handles the core chat functionality including:
- Starting new conversations with initial Bazi analysis
- Processing user messages with RAG-enhanced responses
- Regenerating AI responses
- Managing conversation state
"""
import json
import os
import time
import uuid
from typing import List, Dict, Any, Iterator, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .markdown_utils import normalize_markdown
from .rag import retrieve_kb, resolve_index_dir
from .consultation import bounded_history, consultation_context
from .deepseek_client import call_deepseek, call_deepseek_stream, set_caller
from .sse import should_stream, sse_pack, sse_response
from .store import get_conv, set_conv, append_history, delete_conv
from . import utils
from app.services.completed_reply import save_completed_exchange as _save_db_exchange
from app.services.conversation_report import PERSONAL_TITLES, require_personal_report
from app.core.logging import get_logger

logger = get_logger("chat")

DEFAULT_KB_INDEX = resolve_index_dir("bazi")


def _cache_completed_exchange(cid, question, reply, *, durable):
    try:
        append_history(cid, "user", question)
        append_history(cid, "assistant", reply)
    except Exception as error:
        if not durable:
            raise
        logger.warning("completed_reply_cache_failed", conversation_id=cid, error=str(error))
        from .store import delete_conv
        try:
            delete_conv(cid)
        except Exception:
            pass


# ===================== 数据库持久化辅助函数 =====================

def _parse_db_conversation_id(conversation_id: str) -> Optional[int]:
    """Extract the numeric DB conversation id from current and legacy ids."""
    raw_id = conversation_id
    for prefix in ("bazi_conv_", "conv_"):
        if raw_id.startswith(prefix):
            raw_id = raw_id.removeprefix(prefix)
            break
    return int(raw_id) if raw_id.isdigit() else None


def _create_db_conversation(
    db: Session,
    user_id: int,
    title: str = "八字解读",
    profile_id: Optional[int] = None,
    bazi_chart_snapshot: Optional[Dict[str, Any]] = None,
    task_context: Optional[Dict[str, Any]] = None,
) -> int:
    """创建数据库对话记录，返回对话ID"""
    from app.models.chat import Conversation
    conv = Conversation(
        user_id=user_id,
        title=title,
        profile_id=profile_id,
        bazi_chart_snapshot=bazi_chart_snapshot,
        task_context=task_context,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv.id


# ===================== 对话入口 =====================

def start_chat(
    paipan: Dict[str, Any],
    kb_index_dir: Optional[str],
    kb_topk: int,
    request: Request,
    user_id: Optional[int] = None,
    db: Optional[Session] = None,
    profile_id: Optional[int] = None,
    task_context: Optional[Dict[str, Any]] = None,
):
    """
    Start a new chat conversation with initial Bazi analysis.

    Args:
        paipan: Bazi calculation result (four pillars and dayun)
        kb_index_dir: Knowledge base index directory path
        kb_topk: Number of knowledge base passages to retrieve
        request: FastAPI request object (for streaming detection)
        user_id: Optional user ID for database persistence
        db: Optional database session for persistence
        profile_id: Optional profile ID to bind to this conversation

    Returns:
        StreamingResponse or (conversation_id, reply_text) tuple
    """
    spans: Dict[str, float] = {}
    t0 = utils.now_ms()

    # 数据库对话ID（仅登录用户）
    db_conv_id: Optional[int] = None

    with utils.timer("pre", spans):
        kb_passages: List[str] = []

        # 1）RAG 耗时
        if kb_topk:
            with utils.timer("pre_rag", spans):
                kb_passages = retrieve_kb(
                    "开场上下文",
                    os.path.abspath(kb_index_dir or DEFAULT_KB_INDEX),
                    k=min(3, kb_topk)
                )

        # 2）读 DB 配置耗时
        with utils.timer("pre_db", spans):
            base_prompt = utils.load_report_system_prompt_from_db()

        # 3）拼 system prompt 耗时
        with utils.timer("pre_build_prompt", spans):
            composed = utils.build_full_system_prompt(
                base_prompt,
                kb_passages,
                paipan=paipan,
                include_suggested_questions=False,  # 报告是一次性全量解读，不生成追问
            )

        # 4）初始化会话、写入缓存耗时
        with utils.timer("pre_conv_init", spans):
            # 如果用户已登录，创建数据库记录
            logger.info("start_chat_init", user_id=user_id, db_present=db is not None)
            if user_id and db:
                try:
                    db_conv_id = _create_db_conversation(
                        db, user_id, "八字解读",
                        profile_id=profile_id,
                        bazi_chart_snapshot=paipan,
                        task_context=task_context,
                    )
                    cid = f"bazi_conv_{db_conv_id}"  # 使用数据库ID，添加类型前缀
                    logger.info("db_conversation_created", db_conv_id=db_conv_id, cid=cid, profile_id=profile_id)
                except Exception as e:
                    logger.error("db_conversation_create_failed", error=str(e), user_id=user_id)
                    raise HTTPException(status_code=503, detail="暂时无法创建解读记录，请稍后重试。") from e
            else:
                cid = f"bazi_conv_{uuid.uuid4().hex[:8]}"
                logger.info("anonymous_conversation", cid=cid)

            set_conv(cid, {
                "pinned": composed,
                "history": [],
                "kb_index_dir": os.path.abspath(kb_index_dir or DEFAULT_KB_INDEX),
                "user_id": user_id,
                "db_conv_id": db_conv_id,
                "kind": "bazi",
                "paipan": paipan,
                "task_context": task_context,
            })

        opening_user_msg = (
            f"我的命盘信息如下：\n"
            f"排盘使用的公历日期时间：{paipan.get('solar_date', '')}\n"
            f"性别：{paipan['gender']}\n"
            f"八字：\n{utils.format_four_pillars(paipan['four_pillars'])}\n"
            f"大运：\n{utils.format_dayun(paipan['dayun'])}\n\n"
            "请基于以上命盘做一份通用且全面的解读，条理清晰，"
            "涵盖性格亮点、适合方向、注意点与三年内重点建议。"
            "请按以下七个三级标题依次组织，每章写出实质内容，不省略章节：\n"
            + "\n".join(f"### {title}" for title in PERSONAL_TITLES) + "\n"
            "结尾需要另起一行提醒：以上内容由传统文化AI生成，仅供娱乐参考。"
        )

        messages = [
            {"role": "system", "content": composed},
            {"role": "user", "content": opening_user_msg}
        ]

        logger.debug("chat_start_prompt", conversation_id=cid, messages=messages)

    # —— 流式 —— #
    if should_stream(request):
        def gen() -> Iterator[bytes]:
            nonlocal spans
            first_byte_seen = False
            normalizer = utils.IncrementalNormalizer(normalize_interval=50)
            final = ""  # 初始化，避免 finally 中访问未定义的变量
            assistant_msg_id: Optional[int] = None  # 保存assistant消息ID

            try:
                yield sse_pack(json.dumps({"meta": {"conversation_id": cid}}, ensure_ascii=False))

                start_fb = time.perf_counter()
                set_caller("chat_start")
                for delta in call_deepseek_stream(messages, require_complete=True):
                    if not first_byte_seen:
                        spans["first_byte"] = time.perf_counter() - start_fb
                        first_byte_seen = True

                    if not delta:
                        continue

                    # Use incremental normalizer - only processes every N tokens
                    clean = normalizer.append(delta)
                    if clean:
                        yield sse_pack(json.dumps({"text": clean, "replace": True}, ensure_ascii=False))

                # Final normalization
                final = normalizer.finalize()
                if not final.strip():
                    raise ValueError("empty completed reply")
                require_personal_report(final)
                logger.info("chat_start_final_text", cid=cid, raw_chunks=len(normalizer._raw_chunks), length=len(final), preview=final[:200])
                yield sse_pack(json.dumps({"text": final, "replace": True}, ensure_ascii=False))

                if not first_byte_seen:
                    spans["first_byte"] = time.perf_counter() - start_fb

            except Exception as e:
                logger.error("start_chat_stream_error", error=str(e))
                yield sse_pack(json.dumps({"error": "本次解读未完成，请重新提问。"}, ensure_ascii=False))
                return

            # 必须在 [DONE] 之前持久化。客户端收到 [DONE] 后会主动结束读取，
            # 若把保存放在生成器 finally 中，连接取消时会留下只有会话、没有消息的空记录。
            try:
                if "first_byte" in spans:
                    spans["streaming"] = time.perf_counter() - start_fb - spans["first_byte"]

                with utils.timer("post", spans):
                    # 数据库持久化（仅登录用户）
                    # 注意：流式响应中原 db 会话已关闭，需要创建新会话
                    if db_conv_id and user_id:
                        try:
                            from app.db import SessionLocal
                            with SessionLocal() as new_db:
                                latency = int((utils.now_ms() - t0))
                                assistant_msg_id = _save_db_exchange(new_db, db_conv_id, user_id, opening_user_msg, final, latency_ms=latency, save_profile_report=True)
                                logger.info("messages_persisted", conversation_id=cid, db_conv_id=db_conv_id, assistant_msg_id=assistant_msg_id)
                        except Exception as e:
                            logger.error("message_persist_failed", error=str(e), conversation_id=cid)
                            raise

                    _cache_completed_exchange(cid, opening_user_msg, final, durable=bool(db_conv_id and user_id))

                total_ms = utils.now_ms() - t0
                logger.info("chat_completed",
                    conversation_id=cid,
                    phase_ms=utils.to_ms(spans),
                    total_ms=total_ms,
                    mode="stream_start",
                    kb_topk=kb_topk,
                    db_conv_id=db_conv_id
                )
            except Exception as e:
                logger.error("chat_start_finalize_failed", error=str(e), conversation_id=cid)
                quota_error = isinstance(e, HTTPException) and e.status_code == 429
                yield sse_pack(json.dumps({"error": e.detail if quota_error else "解读未能确认保存，请刷新记录后再试。", "status": 429 if quota_error else 500}, ensure_ascii=False))
                return

            if assistant_msg_id:
                yield sse_pack(json.dumps({"meta": {"message_id": assistant_msg_id}}, ensure_ascii=False))
            yield sse_pack("[DONE]")

        return sse_response(gen)

    # —— 一次性 —— #
    with utils.timer("first_byte", spans):   # 上游整体请求（DeepSeek）算作 first_byte
        set_caller("chat_start")
        reply_raw = call_deepseek(messages, require_complete=True)

    with utils.timer("post", spans):
        reply = normalize_markdown(reply_raw).strip()
        reply = utils.scrub_br_block(reply)
        reply = utils.collapse_double_newlines(reply)
        reply = utils.third_sub(reply)
        # Apply sensitive word filtering
        try:
            from .content_filter import apply_content_filters
            with utils.db_session() as filter_db:
                reply = apply_content_filters(reply, filter_db)
            # 修复敏感词过滤后可能被拆分的标题
            import re
            reply = re.sub(
                r'^(#{1,6}\s+.+?)\n([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]{1,5})\n',
                r'\1\2\n',
                reply,
                flags=re.MULTILINE
            )
            reply = normalize_markdown(reply)
        except Exception:
            pass
        if not reply.strip():
            raise ValueError("empty completed reply")
        require_personal_report(reply)
        # 数据库持久化（仅登录用户）
        if db_conv_id and user_id and db:
            try:
                latency = int((utils.now_ms() - t0))
                _save_db_exchange(db, db_conv_id, user_id, opening_user_msg, reply, latency_ms=latency, save_profile_report=True)
                logger.info("messages_persisted", conversation_id=cid, db_conv_id=db_conv_id)
            except Exception as e:
                logger.error("message_persist_failed", error=str(e), conversation_id=cid)
                raise
        _cache_completed_exchange(cid, opening_user_msg, reply, durable=bool(db_conv_id and user_id))

    total_ms = utils.now_ms() - t0
    logger.info("chat_completed",
        conversation_id=cid,
        phase_ms=utils.to_ms(spans),
        total_ms=total_ms,
        mode="oneshot_start",
        kb_topk=kb_topk,
        db_conv_id=db_conv_id
    )

    return cid, reply


def init_chat(
    user_id: Optional[int] = None,
    db: Optional[Session] = None,
    profile_id: Optional[int] = None,
    paipan: Optional[Dict[str, Any]] = None,
    task_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    初始化会话（不生成 AI 开场白），仅创建会话并返回 conversation_id。
    已登录用户自动从档案读取命盘；也可直接传入 paipan。

    注意：此函数用于 panel 页对话，使用通用 system_prompt（非 report_system_prompt）。
    """
    # 已登录用户从档案读命盘（若未传入 paipan）
    if user_id and db and not paipan:
        from app.models.profile import UserProfile
        profile = db.query(UserProfile).filter_by(user_id=user_id).first()
        if profile:
            profile_id = profile.id
            bazi_chart = profile.bazi_chart
            paipan = bazi_chart.get("mingpan", bazi_chart) if isinstance(bazi_chart, dict) else {}

    # 读 system prompt - 使用通用对话提示词，并注入命盘和实时日期
    base_prompt = utils.load_system_prompt_from_db()
    composed = utils.build_full_system_prompt(base_prompt, [], paipan=paipan)

    # 创建 DB 对话记录（已登录用户）
    db_conv_id: Optional[int] = None
    if user_id and db:
        try:
            db_conv_id = _create_db_conversation(
                db, user_id, "八字解读",
                profile_id=profile_id,
                bazi_chart_snapshot=paipan,
                task_context=task_context,
            )
            cid = f"bazi_conv_{db_conv_id}"
        except Exception as error:
            raise HTTPException(status_code=503, detail="暂时无法创建解读记录，请稍后重试。") from error
    else:
        cid = f"bazi_conv_{uuid.uuid4().hex[:8]}"

    set_conv(cid, {
        "pinned": composed,
        "history": [],
        "kb_index_dir": os.path.abspath(DEFAULT_KB_INDEX),
        "user_id": user_id,
        "db_conv_id": db_conv_id,
        "paipan": paipan or {},
        "kind": "bazi",
        "task_context": task_context,
    })

    logger.info("init_chat_created", cid=cid, user_id=user_id, profile_id=profile_id)
    return cid


def send_chat(
    conversation_id: str,
    message: str,
    request: Request,
    user_id: Optional[int] = None,
    db: Optional[Session] = None,
    display_message: Optional[str] = None,
    task_context: Optional[Dict[str, Any]] = None,
):
    """
    Send a message in an existing conversation.

    Args:
        conversation_id: Existing conversation ID
        message: User message content
        request: FastAPI request object (for streaming detection)
        user_id: Current user ID for ownership check and DB recovery
        db: Optional database session for persistence

    Returns:
        StreamingResponse or reply_text string

    Raises:
        ValueError: If conversation doesn't exist or user doesn't own it
    """
    conv = get_conv(conversation_id)

    # 如果会话不存在且用户已登录，尝试从数据库恢复
    if not conv and user_id and db:
        logger.info("conversation_not_found_attempting_recovery", conversation_id=conversation_id, user_id=user_id)
        try:
            from app.models.chat import Conversation as ConvModel, Message as MsgModel
            db_conv_id_int = _parse_db_conversation_id(conversation_id)

            if db_conv_id_int:
                db_conv = db.get(ConvModel, db_conv_id_int)
                if (
                    db_conv
                    and db_conv.user_id == user_id
                    and (db_conv.profile_id is not None or db_conv.bazi_chart_snapshot)
                    and db_conv.liuyao_hexagram_id is None
                ):
                    # 用会话创建时的命盘快照（而非当前 live profile）
                    snapshot = db_conv.bazi_chart_snapshot or {}
                    paipan = snapshot.get("mingpan", snapshot) if isinstance(snapshot, dict) else {}

                    # 若快照为空则 fallback 到当前 profile
                    if not paipan:
                        from app.models.profile import UserProfile
                        profile = db.query(UserProfile).filter_by(user_id=user_id).first()
                        if profile and profile.bazi_chart:
                            bazi_chart = profile.bazi_chart
                            paipan = bazi_chart.get("mingpan", bazi_chart) if isinstance(bazi_chart, dict) else {}

                    base_prompt = utils.load_system_prompt_from_db()
                    composed = utils.build_full_system_prompt(base_prompt, [], paipan=paipan)

                    # 从 DB 恢复历史消息，确保 AI 能看到之前的对话
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
                        "pinned": composed,
                        "history": history,
                        "kb_index_dir": os.path.abspath(DEFAULT_KB_INDEX),
                        "user_id": user_id,
                        "db_conv_id": db_conv_id_int,
                        "paipan": paipan,
                        "kind": "bazi",
                        "task_context": db_conv.task_context,
                    })
                    conv = get_conv(conversation_id)
                    logger.info("conversation_recovered", conversation_id=conversation_id, user_id=user_id, msg_count=len(history))
        except Exception as e:
            logger.error("conversation_recovery_failed", error=str(e), conversation_id=conversation_id)

    if not conv:
        raise ValueError("会话不存在，请先 /chat/start")

    # 所有权校验：已登录用户只能访问自己的会话
    conv_user_id = conv.get("user_id")
    if conv_user_id is not None and conv_user_id != user_id:
        raise ValueError("会话不存在，请先 /chat/start")

    # 获取持久化信息
    user_id = conv.get("user_id")
    db_conv_id = conv.get("db_conv_id")
    if db_conv_id and db:
        from app.models.chat import Conversation, Message
        db_conv = db.get(Conversation, db_conv_id)
        if not db_conv or db_conv.user_id != user_id or db_conv.liuyao_hexagram_id is not None:
            raise ValueError("会话不存在，请先 /chat/start")
        # Once attached, the original question/facts belong to this conversation.
        # A stale browser's task must not rewrite the saved report background.
        if db_conv.task_context is None and task_context:
            db_conv.task_context = task_context
            db.commit()
        conv["task_context"] = db_conv.task_context
        # A worker's memory (or a Redis read-modify-write race) may omit a
        # committed reply. Saved messages are the authoritative prompt history.
        conv = dict(conv)
        conv["history"] = [
            {"role": row.role, "content": row.content}
            for row in db.query(Message).filter_by(conversation_id=db_conv_id)
            .order_by(Message.id).all() if row.role in ("user", "assistant")
        ]
        snapshot = db_conv.bazi_chart_snapshot or {}
        if snapshot:
            conv["paipan"] = snapshot.get("mingpan", snapshot)
    elif task_context and not conv.get("task_context"):
        conv["task_context"] = task_context

    # 查找本地知识库
    kb_dir = conv.get("kb_index_dir")
    kb_passages: List[str] = []
    if kb_dir and os.path.exists(os.path.join(kb_dir, "chunks.json")):
        try:
            kb_passages = retrieve_kb(message, kb_dir, k=3)
        except Exception:
            kb_passages = []

    # 每次对话都从 DB 重新加载最新 system prompt，确保管理员改动立即生效
    paipan = conv.get("paipan") or {}
    base_prompt = utils.load_system_prompt_from_db()
    composed = utils.build_full_system_prompt(base_prompt, kb_passages, paipan=paipan)

    # 注入本命八字锚点：避免对话中出现多个八字时混淆（如合盘、家人八字等）
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
            f"2. 若用户在对话中提到他人八字（如配偶、合盘对象、家人），仅作参考对比\n"
            f"3. 除非用户明确指定分析对象，否则默认所有问题都是关于用户本命盘\n"
            f"4. 不要将其他人的八字信息覆盖或替换用户的本命盘"
        )
        composed = composed + bazi_anchor

    recentN = 10
    history = conv.get("history", [])
    messages = [{"role": "system", "content": composed}]

    # 第一条消息时，前置注入命盘数据作为上下文
    if not history:
        paipan = conv.get("paipan") or {}
        if paipan and paipan.get("four_pillars") and paipan.get("dayun"):
            paipan_context = (
                f"我的命盘信息如下：\n"
                f"排盘使用的公历日期时间：{paipan.get('solar_date', '')}\n"
                f"性别：{paipan.get('gender', '')}\n"
                f"八字：\n{utils.format_four_pillars(paipan['four_pillars'])}\n"
                f"大运：\n{utils.format_dayun(paipan['dayun'])}"
            )
            messages.append({"role": "user", "content": paipan_context})
            messages.append({"role": "assistant", "content": "好的，我已收到您的命盘信息，请问您想了解什么？"})

    messages.extend(consultation_context(db, conv.get("task_context"), history))
    messages.extend(bounded_history(history, recentN))
    messages.append({"role": "user", "content": message})

    logger.debug("chat_send_prompt", conversation_id=conversation_id, message=message)

    t0 = utils.now_ms()
    persisted_user_message = (display_message or message).strip() or message

    # 流式
    if should_stream(request):
        def gen() -> Iterator[bytes]:
            normalizer = utils.IncrementalNormalizer(normalize_interval=50)
            final = ""  # 初始化，避免 finally 中访问未定义的变量
            assistant_msg_id: Optional[int] = None  # 保存assistant消息ID
            try:
                yield sse_pack(json.dumps({"meta": {"conversation_id": conversation_id}}, ensure_ascii=False))
                set_caller("chat_send")
                for delta in call_deepseek_stream(messages, require_complete=True):
                    if not delta:
                        continue
                    # Use incremental normalizer
                    clean = normalizer.append(delta)
                    if clean:
                        yield sse_pack(json.dumps({"text": clean, "replace": True}, ensure_ascii=False))

                # Final normalization
                final = normalizer.finalize()
                if not final.strip():
                    raise ValueError("empty completed reply")
                yield sse_pack(json.dumps({"text": final, "replace": True}, ensure_ascii=False))
            except Exception as e:
                logger.error("send_chat_stream_error", error=str(e))
                yield sse_pack(json.dumps({"error": "本次解读未完成，请重新提问。"}, ensure_ascii=False))
                return

            # 与 start_chat 一致：先保存，再宣告流结束。
            try:
                # 数据库持久化（仅登录用户）
                # 注意：流式响应中原 db 会话已关闭，需要创建新会话
                if db_conv_id and user_id:
                    try:
                        from app.db import SessionLocal
                        with SessionLocal() as new_db:
                            latency = int((utils.now_ms() - t0))
                            assistant_msg_id = _save_db_exchange(new_db, db_conv_id, user_id, persisted_user_message, final, latency_ms=latency)
                            logger.info("messages_persisted", conversation_id=conversation_id, assistant_msg_id=assistant_msg_id)
                    except Exception as e:
                        logger.error("message_persist_failed", error=str(e), conversation_id=conversation_id)
                        raise
                _cache_completed_exchange(conversation_id, persisted_user_message, final, durable=bool(db_conv_id and user_id))
            except Exception as e:
                logger.error("chat_send_finalize_failed", error=str(e), conversation_id=conversation_id)
                quota_error = isinstance(e, HTTPException) and e.status_code == 429
                yield sse_pack(json.dumps({"error": e.detail if quota_error else "解读未能确认保存，请刷新记录后再试。", "status": 429 if quota_error else 500}, ensure_ascii=False))
                return

            if assistant_msg_id:
                yield sse_pack(json.dumps({"meta": {"message_id": assistant_msg_id}}, ensure_ascii=False))
            yield sse_pack("[DONE]")

        return sse_response(gen)

    # 一次性
    set_caller("chat_send")
    reply = normalize_markdown(call_deepseek(messages, require_complete=True)).strip()
    reply = utils.scrub_br_block(reply)
    reply = utils.collapse_double_newlines(reply)
    reply = utils.third_sub(reply)
    # Apply sensitive word filtering
    try:
        from .content_filter import apply_content_filters
        with utils.db_session() as filter_db:
            reply = apply_content_filters(reply, filter_db)
        # 修复敏感词过滤后可能被拆分的标题
        import re
        reply = re.sub(
            r'^(#{1,6}\s+.+?)\n([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]{1,5})\n',
            r'\1\2\n',
            reply,
            flags=re.MULTILINE
        )
        reply = normalize_markdown(reply)
    except Exception:
        pass
    if not reply.strip():
        raise ValueError("empty completed reply")
    # 数据库持久化（仅登录用户）
    if db_conv_id and user_id and db:
        try:
            latency = int((utils.now_ms() - t0))
            _save_db_exchange(db, db_conv_id, user_id, persisted_user_message, reply, latency_ms=latency)
        except Exception as e:
            logger.error("message_persist_failed", error=str(e), conversation_id=conversation_id)
            raise
    _cache_completed_exchange(conversation_id, persisted_user_message, reply, durable=bool(db_conv_id and user_id))

    return reply

def regenerate(conversation_id: str, user_id: Optional[int] = None, db=None, expected_message_id=None):
    """
    Regenerate the last AI response in a conversation.

    Args:
        conversation_id: Existing conversation ID
        user_id: Current user ID for ownership check and DB recovery

    Returns:
        Newly generated reply and its saved message ID; the original is retained.

    Raises:
        ValueError: If conversation doesn't exist or can't be regenerated
    """
    from app.services.conversation_actions import owned_conversation, saved_messages, append_regeneration
    target_id = None
    db_conv_id = None
    if user_id is not None:
        saved = owned_conversation(db, conversation_id, user_id, 'bazi')
        rows = saved_messages(db, saved.id)
        if not rows or rows[-1].role != 'assistant':
            raise ValueError('还没有已保存的完整回复，不能重新解读。')
        target_id = rows[-1].id
        if expected_message_id is not None and target_id != expected_message_id:
            raise HTTPException(409, '会话已有新的回复，请重新加载后再重新解读。')
        db_conv_id = saved.id
        snapshot = saved.bazi_chart_snapshot or {}
        conv = {'user_id': user_id, 'history': [{'role': row.role, 'content': row.content} for row in rows if row.role in ('user', 'assistant')],
                'paipan': snapshot.get('mingpan', snapshot), 'task_context': saved.task_context, 'kb_index_dir': DEFAULT_KB_INDEX}
    else:
        conv = get_conv(conversation_id)
    if not conv:
        raise ValueError("会话不存在，请先 /chat/start")

    # 所有权校验
    conv_user_id = conv.get("user_id")
    if conv_user_id is not None and conv_user_id != user_id:
        raise ValueError("会话不存在，请先 /chat/start")

    history = bounded_history(conv.get("history", []), len(conv.get('history', [])) or 1)
    if not history:
        raise ValueError("历史为空，无法重生")
    if history[-1]["role"] != "assistant":
        raise ValueError("最后一条不是 assistant，无法重生")

    # Do not mutate live history before the upstream request succeeds. Otherwise
    # a timeout/error makes the original answer disappear from conversation
    # context and the next retry fails with "最后一条不是 assistant".
    retry_history = history[:-1]

    last_user_msg = None
    for m in reversed(retry_history):
        if m["role"] == "user":
            last_user_msg = m["content"]
            break
    if not last_user_msg:
        last_user_msg = "请基于以上上下文继续完善上一轮解读。"

    kb_dir = conv.get("kb_index_dir")
    kb_passages: List[str] = []
    if kb_dir and os.path.exists(os.path.join(kb_dir, "chunks.json")):
        try:
            kb_passages = retrieve_kb(last_user_msg, kb_dir, k=3)
        except Exception:
            kb_passages = []

    is_opening_report = (
        len(retry_history) == 1
        and retry_history[0].get("role") == "user"
        and "我的命盘信息如下" in retry_history[0].get("content", "")
    )
    base_prompt = (
        utils.load_report_system_prompt_from_db()
        if is_opening_report
        else utils.load_system_prompt_from_db()
    )
    paipan = conv.get("paipan") or {}
    composed = utils.build_full_system_prompt(
        base_prompt,
        kb_passages,
        paipan=paipan,
        include_suggested_questions=not is_opening_report,  # 报告重生成不需要追问
    )

    # 注入本命八字锚点：避免对话中出现多个八字时混淆
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
            f"2. 若用户在对话中提到他人八字（如配偶、合盘对象、家人），仅作参考对比\n"
            f"3. 除非用户明确指定分析对象，否则默认所有问题都是关于用户本命盘\n"
            f"4. 不要将其他人的八字信息覆盖或替换用户的本命盘"
        )
        composed = composed + bazi_anchor

    recentN = 10
    messages = [{"role": "system", "content": composed}]
    if (conv.get("task_context") or {}).get("taskType") == "career":
        messages.extend(consultation_context(db, conv.get("task_context"), retry_history))
    messages.extend(bounded_history(retry_history, recentN))

    set_caller("regenerate")
    reply = normalize_markdown(call_deepseek(messages, require_complete=True)).strip()
    # Apply sensitive word filtering
    try:
        from .content_filter import apply_content_filters
        with utils.db_session() as filter_db:
            reply = apply_content_filters(reply, filter_db)
        # 修复敏感词过滤后可能被拆分的标题
        import re
        reply = re.sub(
            r'^(#{1,6}\s+.+?)\n([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]{1,5})\n',
            r'\1\2\n',
            reply,
            flags=re.MULTILINE
        )
        reply = normalize_markdown(reply)
    except Exception:
        pass
    if not reply.strip():
        raise ValueError('AI 服务未返回完整内容，原回答已保留。')
    if is_opening_report:
        require_personal_report(reply)
    message_id = None
    if db_conv_id is not None:
        message_id = append_regeneration(db, db_conv_id, user_id, target_id, reply, 'bazi')
        try:
            delete_conv(conversation_id)
        except Exception:
            logger.warning('regeneration_cache_invalidation_failed', conversation_id=conversation_id)
    else:
        new_conv = dict(conv)
        new_conv['history'] = [*conv.get('history', []), {'role': 'assistant', 'content': reply}]
        set_conv(conversation_id, new_conv)
    return {'reply': reply, 'message_id': message_id}


def simplify_message(message_content: str, request: Request):
    """
    Rewrite professional Bazi analysis into plain Chinese (白话版).
    Does not read or write conversation history.
    """
    system_prompt = (
        "你是命理内容转化助手。将用户提供的专业命理解读改写为大众白话文。\n"
        "要求：\n"
        "1. 保留核心结论，不添加原文没有的内容\n"
        "2. 专业术语用括号附简单解释（如：印星（代表贵人和支持力量））\n"
        "3. 语言口语化亲切，避免晦涩词汇\n"
        "4. 长度控制在原文50-70%\n"
        "5. 直接输出改写后的内容，不要任何前言"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请将以下命理解读改写为白话文：\n\n{message_content}"},
    ]

    if should_stream(request):
        def gen() -> Iterator[bytes]:
            try:
                set_caller("simplify")
                normalizer = utils.IncrementalNormalizer(normalize_interval=50)
                for delta in call_deepseek_stream(messages):
                    if not delta:
                        continue
                    clean = normalizer.append(delta)
                    if clean:
                        yield sse_pack(json.dumps({"text": clean, "replace": True}, ensure_ascii=False))
                final = normalizer.finalize()
                yield sse_pack(json.dumps({"text": final, "replace": True}, ensure_ascii=False))
                yield sse_pack("[DONE]")
            except Exception as e:
                logger.error("simplify_stream_error", error=str(e))
                yield sse_pack(json.dumps({"text": "抱歉，本次解读生成失败。你可以刷新页面后重新提问，或稍后再试。", "replace": True}, ensure_ascii=False))
                yield sse_pack("[DONE]")

        return sse_response(gen)

    set_caller("simplify")
    reply = normalize_markdown(call_deepseek(messages)).strip()
    reply = utils.scrub_br_block(reply)
    reply = utils.collapse_double_newlines(reply)
    reply = utils.third_sub(reply)
    return {"content": reply}


def clear(conversation_id: str, user_id=None, db=None):
    """
    Start an empty conversation with the original chart and retain the archive.

    Args:
        conversation_id: Existing conversation ID

    Returns:
        Dict with "ok" and the new "conversation_id".
    """
    from app.services.conversation_actions import owned_conversation, fresh_bazi_conversation
    if user_id is not None:
        original = owned_conversation(db, conversation_id, user_id, 'bazi')
        cid = f'bazi_conv_{fresh_bazi_conversation(db, original)}'
    else:
        original = get_conv(conversation_id)
        if not original or original.get('user_id') is not None or original.get('kind') == 'liuyao':
            raise ValueError('会话不存在')
        cid = f'bazi_conv_{uuid.uuid4().hex[:8]}'
        set_conv(cid, {**original, 'history': [], 'task_context': None})
    return {'ok': True, 'conversation_id': cid}
