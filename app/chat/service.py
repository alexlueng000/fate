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

from fastapi import Request
from fastapi.responses import StreamingResponse

from .markdown_utils import normalize_markdown
from .rag import retrieve_kb
from .deepseek_client import call_deepseek, call_deepseek_stream
from .sse import should_stream, sse_pack, sse_response
from .store import get_conv, set_conv, append_history, clear_history
from . import utils
from app.core.logging import get_logger

logger = get_logger("chat")

DEFAULT_KB_INDEX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "kb_index"))


# ===================== 对话入口 =====================

def start_chat(paipan: Dict[str, Any], kb_index_dir: Optional[str], kb_topk: int, request: Request):
    """
    Start a new chat conversation with initial Bazi analysis.

    Args:
        paipan: Bazi calculation result (four pillars and dayun)
        kb_index_dir: Knowledge base index directory path
        kb_topk: Number of knowledge base passages to retrieve
        request: FastAPI request object (for streaming detection)

    Returns:
        StreamingResponse or (conversation_id, reply_text) tuple
    """
    spans: Dict[str, float] = {}
    t0 = utils.now_ms()

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
            base_prompt = utils.load_system_prompt_from_db()

        # 3）拼 system prompt 耗时
        with utils.timer("pre_build_prompt", spans):
            composed = utils.build_full_system_prompt(
                base_prompt,
                {"four_pillars": paipan["four_pillars"], "dayun": paipan["dayun"], "gender": paipan["gender"]},
                kb_passages
            )

        # 4）初始化会话、写入缓存耗时
        with utils.timer("pre_conv_init", spans):
            cid = f"conv_{uuid.uuid4().hex[:8]}"
            set_conv(cid, {
                "pinned": composed,
                "history": [],
                "kb_index_dir": os.path.abspath(kb_index_dir or DEFAULT_KB_INDEX)
            })

        opening_user_msg = (
            "请基于以上命盘做一份通用且全面的解读，条理清晰，"
            "涵盖性格亮点、适合方向、注意点与三年内重点建议。"
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

            try:
                yield sse_pack(json.dumps({"meta": {"conversation_id": cid}}, ensure_ascii=False))

                start_fb = time.perf_counter()
                for delta in call_deepseek_stream(messages):
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
                yield sse_pack(json.dumps({"text": final, "replace": True}, ensure_ascii=False))

                if not first_byte_seen:
                    spans["first_byte"] = time.perf_counter() - start_fb

                yield sse_pack("[DONE]")

            except Exception as e:
                yield sse_pack(f"[ERROR]{str(e)}")

            finally:
                if "first_byte" in spans:
                    spans["streaming"] = time.perf_counter() - start_fb - spans["first_byte"]

                with utils.timer("post", spans):
                    append_history(cid, "user", opening_user_msg)
                    append_history(cid, "assistant", final)

                total_ms = utils.now_ms() - t0
                logger.info("chat_completed",
                    conversation_id=cid,
                    phase_ms=utils.to_ms(spans),
                    total_ms=total_ms,
                    mode="stream_start",
                    kb_topk=kb_topk
                )

        return sse_response(gen)

    # —— 一次性 —— #
    with utils.timer("first_byte", spans):   # 上游整体请求（DeepSeek）算作 first_byte
        reply_raw = call_deepseek(messages)

    with utils.timer("post", spans):
        reply = normalize_markdown(reply_raw).strip()
        reply = utils.scrub_br_block(reply)
        reply = utils.collapse_double_newlines(reply)
        reply = utils.third_sub(reply)
        # Apply sensitive word filtering
        try:
            from .content_filter import apply_content_filters
            with utils.db_session() as db:
                reply = apply_content_filters(reply, db)
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
        append_history(cid, "user", opening_user_msg)
        append_history(cid, "assistant", reply)

    total_ms = utils.now_ms() - t0
    logger.info("chat_completed",
        conversation_id=cid,
        phase_ms=utils.to_ms(spans),
        total_ms=total_ms,
        mode="oneshot_start",
        kb_topk=kb_topk
    )

    return cid, reply


def send_chat(conversation_id: str, message: str, request: Request):
    """
    Send a message in an existing conversation.

    Args:
        conversation_id: Existing conversation ID
        message: User message content
        request: FastAPI request object (for streaming detection)

    Returns:
        StreamingResponse or reply_text string

    Raises:
        ValueError: If conversation doesn't exist
    """
    conv = get_conv(conversation_id)
    if not conv:
        raise ValueError("会话不存在，请先 /chat/start")

    # 查找本地知识库
    kb_dir = conv.get("kb_index_dir")
    kb_passages: List[str] = []
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

    logger.debug("chat_send_prompt", conversation_id=conversation_id, message=message)

    # 流式
    if should_stream(request):
        def gen() -> Iterator[bytes]:
            normalizer = utils.IncrementalNormalizer(normalize_interval=50)
            final = ""  # 初始化，避免 finally 中访问未定义的变量
            try:
                yield sse_pack(json.dumps({"meta": {"conversation_id": conversation_id}}, ensure_ascii=False))
                for delta in call_deepseek_stream(messages):
                    if not delta:
                        continue
                    # Use incremental normalizer
                    clean = normalizer.append(delta)
                    if clean:
                        yield sse_pack(json.dumps({"text": clean, "replace": True}, ensure_ascii=False))

                # Final normalization
                final = normalizer.finalize()
                yield sse_pack(json.dumps({"text": final, "replace": True}, ensure_ascii=False))
                yield sse_pack("[DONE]")
            except Exception as e:
                yield sse_pack(f"[ERROR]{str(e)}")
            finally:
                append_history(conversation_id, "user", message)
                append_history(conversation_id, "assistant", final)
        return sse_response(gen)

    # 一次性
    reply = normalize_markdown(call_deepseek(messages)).strip()
    reply = utils.scrub_br_block(reply)
    reply = utils.collapse_double_newlines(reply)
    reply = utils.third_sub(reply)
    # Apply sensitive word filtering
    try:
        from .content_filter import apply_content_filters
        with utils.db_session() as db:
            reply = apply_content_filters(reply, db)
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
    append_history(conversation_id, "user", message)
    append_history(conversation_id, "assistant", reply)
    return reply

def regenerate(conversation_id: str) -> str:
    """
    Regenerate the last AI response in a conversation.

    Args:
        conversation_id: Existing conversation ID

    Returns:
        Newly generated reply text

    Raises:
        ValueError: If conversation doesn't exist or can't be regenerated
    """
    conv = get_conv(conversation_id)
    if not conv:
        raise ValueError("会话不存在，请先 /chat/start")

    history = conv.get("history", [])
    if not history:
        raise ValueError("历史为空，无法重生")
    if history[-1]["role"] != "assistant":
        raise ValueError("最后一条不是 assistant，无法重生")

    history.pop()  # 删除最后一条 assistant

    last_user_msg = None
    for m in reversed(history):
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

    composed = conv["pinned"]
    if kb_passages:
        kb_block = "\n\n".join(kb_passages)
        composed = f"{composed}\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"

    recentN = 10
    trimmed_history = history[-recentN:]
    messages = [{"role": "system", "content": composed}]
    messages.extend(trimmed_history)

    reply = normalize_markdown(call_deepseek(messages))
    # Apply sensitive word filtering
    try:
        from .content_filter import apply_content_filters
        with utils.db_session() as db:
            reply = apply_content_filters(reply, db)
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
    append_history(conversation_id, "assistant", reply)
    return reply


def clear(conversation_id: str) -> Dict[str, bool]:
    """
    Clear conversation history while keeping the system prompt.

    Args:
        conversation_id: Existing conversation ID

    Returns:
        Dict with "ok" key indicating success
    """
    ok = clear_history(conversation_id, keep_pinned=True)
    return {"ok": ok}