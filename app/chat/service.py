# app/chat/service.py
import os
import re
import uuid
import json
import time
from typing import List, Dict, Any, Iterator, Optional
from contextlib import contextmanager

from fastapi.responses import StreamingResponse
from fastapi import Request
from sqlalchemy import text

from ..db import get_db  # 依赖你的 Session 生成器

# from ..utils.prompts import SYSTEM_PROMPT  # ← 不再直接使用常量，改为 DB 读取

from .markdown_utils import normalize_markdown
from .rag import retrieve_kb
from .deepseek_client import call_deepseek, call_deepseek_stream
from .sse import should_stream, sse_pack, sse_response
from .store import get_conv, set_conv, append_history, clear_history

DEFAULT_KB_INDEX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "kb_index"))

# 只清理形如  \n<br/>\n\n / \r\n<br />\r\n\r\n 的块；大小写不敏感
_BR_BLOCK = re.compile(r"(?:\r?\n)?<br\s*/?>\s*(?:\r?\n){2}", re.IGNORECASE)
_BR_REPLACEMENT = "\n- "

def _scrub_br_block(s: str) -> str:
    return _BR_BLOCK.sub(_BR_REPLACEMENT, s)

# 把所有 2+ 个连续换行压成 1 个换行：\n\n -> \n（兼容 \r\n）
_MULTI_NL = re.compile(r"(?:\r?\n){2,}")

def _collapse_double_newlines(s: str) -> str:
    return _MULTI_NL.sub("\n", s)

def _third_sub(s: str) -> str:
    return s.replace("\n- -", "\n-")

def _append_md_rules(prompt: str) -> str:
    rules = (
        "\n\n【输出格式要求】\n"
        "- 全文使用 Markdown。\n"
        "- 标题只能使用 `###`（一级）、`####`（二级），禁止使用其他层级。\n"
        "- 标题写法：`### 标题`（# 后必须有空格），且**标题必须独占一行**，标题前后**各空一行**。\n"
        "- 段落与段落之间必须空一行。\n"
        "- 列表项必须独立换行，使用 `- ` 或 `1. `。\n"
        "- **禁止使用粗体/斜体/引用/分割线**；如需强调请用全角符号【】。\n"
        "- 禁止复杂嵌套。\n"
        "- 输出遵循最基础、最兼容的 Markdown 子集，确保前端解析稳定。\n"
    )
    return f"{prompt}\n{rules}"

def _format_four_pillars(fp: Dict[str, List[str]]) -> str:
    return (
        f"年柱: {''.join(fp['year'])}\n"
        f"月柱: {''.join(fp['month'])}\n"
        f"日柱: {''.join(fp['day'])}\n"
        f"时柱: {''.join(fp['hour'])}"
    )

def _format_dayun(dy: List[Dict[str, Any]]) -> str:
    lines = []
    for item in dy:
        pillar = "".join(item["pillar"])
        lines.append(f"- 起始年龄 {item['age']}，起运年 {item['start_year']}，大运 {pillar}")
    return "\n".join(lines)

# ===================== 新增：读取 DB 配置 =====================

@contextmanager
def _db_session():
    """安全获取并关闭 DB session（基于你项目里的 get_db 生成器）"""
    db = next(get_db())
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception:
            pass

def _parse_value_json(v: Any) -> Dict[str, Any]:
    """兼容 JSON/字符串化 JSON 两种返回"""
    if v is None:
        return {}
    if isinstance(v, (dict, list)):
        return v if isinstance(v, dict) else {}
    if isinstance(v, str):
        try:
            data = json.loads(v)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def _fetch_latest_config(db, key: str) -> Optional[Dict[str, Any]]:
    """
    读取 app_config（或你实际表名）里最新版本。
    这里用原生 SQL；如果你有 ORM Model，可以替换为 ORM 查询。
    """
    sql = """
        SELECT `cfg_key`, `version`, `value_json`
        FROM `app_config`
        WHERE `cfg_key` = :key
        ORDER BY `version` DESC
        LIMIT 1
    """
    # 关键：用 text(sql)
    row = db.execute(text(sql), {"key": key}).mappings().first()
    if not row:
        return None
    return {
        "key": row["cfg_key"],
        "version": row["version"],
        "value_json": _parse_value_json(row["value_json"]),
    }

def _load_system_prompt_from_db() -> str:
    """
    优先读取 system_prompt，若不存在回退 rprompt。
    结构期望：value_json = { "content": "......", "notes": "..." }
    """
    with _db_session() as db:
        cfg = _fetch_latest_config(db, "system_prompt")
        if not cfg:
            cfg = _fetch_latest_config(db, "rprompt")
        if not cfg:
            return ""  # 兜底空串（也可回退到旧常量）
        content = (cfg["value_json"] or {}).get("content")
        return content or ""

# ===================== 拼装 System Prompt =====================

def build_full_system_prompt(base_prompt: str, mingpan: Dict[str, Any], kb_passages: List[str]) -> str:
    """
    由 DB 加载的 base_prompt，填充 {FOUR_PILLARS}/{DAYUN}，并附加格式规则与 KB 片段
    """
    fp_text = _format_four_pillars(mingpan["four_pillars"])
    dy_text = _format_dayun(mingpan["dayun"])
    composed = (base_prompt or "")
    composed = composed.replace("{FOUR_PILLARS}", fp_text).replace("{DAYUN}", dy_text)
    if kb_passages:
        kb_block = "\n\n".join(kb_passages[:3])
        composed += f"\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"
    return _append_md_rules(composed)


# ==================== 时间统计函数 ====================

@contextmanager
def _t(section: str, spans: Dict[str, float]):
    s = time.perf_counter()
    try:
        yield
    finally:
        spans[section] = time.perf_counter() - s

def _now_ms() -> int:
    return int(time.time() * 1000)

def _ms(spans: Dict[str, float]) -> Dict[str, int]:
    # 秒 -> 毫秒并取整
    return {k: int(v * 1000) for k, v in spans.items()}


# ===================== 对话入口 =====================


# ===================== 对话入口 =====================

def start_chat(paipan: Dict[str, Any], kb_index_dir: Optional[str], kb_topk: int, request: Request):
    spans: Dict[str, float] = {}
    t0 = _now_ms()

    with _t("pre", spans):
        kb_passages: List[str] = []

        # 1）RAG 耗时
        if kb_topk:
            with _t("pre_rag", spans):
                kb_passages = retrieve_kb(
                    "开场上下文",
                    os.path.abspath(kb_index_dir or DEFAULT_KB_INDEX),
                    k=min(3, kb_topk)
                )

        # 2）读 DB 配置耗时
        with _t("pre_db", spans):
            base_prompt = _load_system_prompt_from_db()

        # 3）拼 system prompt 耗时
        with _t("pre_build_prompt", spans):
            composed = build_full_system_prompt(
                base_prompt,
                {"four_pillars": paipan["four_pillars"], "dayun": paipan["dayun"]},
                kb_passages
            )

        # 4）初始化会话、写入缓存耗时
        with _t("pre_conv_init", spans):
            cid = f"conv_{uuid.uuid4().hex[:8]}"
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

        print("首次对话prompt: ", messages)

    # —— 流式 —— #
    if should_stream(request):
        def gen() -> Iterator[bytes]:
            nonlocal spans
            full: List[str] = []
            first_byte_seen = False
            try:
                yield sse_pack(json.dumps({"meta": {"conversation_id": cid}}, ensure_ascii=False))

                start_fb = time.perf_counter()
                for delta in call_deepseek_stream(messages):
                    if not first_byte_seen:
                        spans["first_byte"] = time.perf_counter() - start_fb
                        first_byte_seen = True

                    if not delta:
                        continue
                    full.append(delta)

                    clean = normalize_markdown("".join(full))
                    clean = _scrub_br_block(clean)
                    clean = _collapse_double_newlines(clean)
                    clean = _third_sub(clean)

                    yield sse_pack(json.dumps({"text": clean, "replace": True}, ensure_ascii=False))

                if not first_byte_seen:
                    spans["first_byte"] = time.perf_counter() - start_fb

                yield sse_pack("[DONE]")

            except Exception as e:
                yield sse_pack(f"[ERROR]{str(e)}")

            finally:
                if "first_byte" in spans:
                    spans["streaming"] = time.perf_counter() - start_fb - spans["first_byte"]

                with _t("post", spans):
                    final = normalize_markdown("".join(full)).strip()
                    final = _scrub_br_block(final)
                    final = _collapse_double_newlines(final)
                    final = _third_sub(final)
                    append_history(cid, "user", opening_user_msg)
                    append_history(cid, "assistant", final)

                total_ms = _now_ms() - t0
                print({
                    "cid": cid,
                    "phase_ms": _ms(spans),
                    "t_total_ms": total_ms,
                    "mode": "stream_start",
                    "kb_topk": kb_topk,
                })

        return sse_response(gen)

    # —— 一次性 —— #
    with _t("first_byte", spans):   # 上游整体请求（DeepSeek）算作 first_byte
        reply_raw = call_deepseek(messages)

    with _t("post", spans):
        reply = normalize_markdown(reply_raw).strip()
        reply = _scrub_br_block(reply)
        reply = _collapse_double_newlines(reply)
        reply = _third_sub(reply)
        append_history(cid, "user", opening_user_msg)
        append_history(cid, "assistant", reply)

    total_ms = _now_ms() - t0
    print({
        "cid": cid,
        "phase_ms": _ms(spans),
        "t_total_ms": total_ms,
        "mode": "oneshot_start",
        "kb_topk": kb_topk,
    })

    return cid, reply


def send_chat(conversation_id: str, message: str, request: Request):

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

    print("后续对话prompt: ", message)

    # 流式
    if should_stream(request):
        def gen() -> Iterator[bytes]:
            full: List[str] = []
            try:
                yield sse_pack(json.dumps({"meta": {"conversation_id": conversation_id}}, ensure_ascii=False))
                for delta in call_deepseek_stream(messages):
                    if not delta:
                        continue
                    full.append(delta)
                    clean = normalize_markdown("".join(full))
                    clean = _scrub_br_block(clean)              # ← 新增兜底替换
                    clean = _collapse_double_newlines(clean)     # ← 新增：把 \n\n 压成 \n
                    clean = _third_sub(clean)                    # ← 新增：把 \n\n 压成 \n
                    yield sse_pack(json.dumps({"text": clean, "replace": True}, ensure_ascii=False))
                yield sse_pack("[DONE]")
            except Exception as e:
                yield sse_pack(f"[ERROR]{str(e)}")
            finally:
                final = normalize_markdown("".join(full)).strip()
                final = _scrub_br_block(final)                 # ← 新增兜底保存
                final = _collapse_double_newlines(final)        # ← 新增：把 \n\n 压成 \n
                final = _third_sub(final)                        # ← 新增：把 \n\n 压成 \n
                append_history(conversation_id, "user", message)
                append_history(conversation_id, "assistant", final)
        return sse_response(gen)

    # 一次性
    reply = normalize_markdown(call_deepseek(messages)).strip()
    reply = _scrub_br_block(reply)                             # ← 新增兜底替换
    reply = _collapse_double_newlines(reply)                    # ← 新增：把 \n\n 压成 \n
    reply = _third_sub(reply)                                  # ← 新增：把 \n\n 压成 \n
    append_history(conversation_id, "user", message)
    append_history(conversation_id, "assistant", reply)
    return reply

def regenerate(conversation_id: str) -> str:
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
    append_history(conversation_id, "assistant", reply)
    return reply


def clear(conversation_id: str):
    ok = clear_history(conversation_id, keep_pinned=True)
    return {"ok": ok}