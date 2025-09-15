# app/chat/service.py
import os
import re
import uuid
import json
from typing import List, Dict, Any, Iterator, Optional

from fastapi.responses import StreamingResponse
from fastapi import Request

from ..db import get_db  # 保持你的依赖路径
from ..utils.prompts import SYSTEM_PROMPT

from .markdown_utils import normalize_markdown
from .rag import retrieve_kb
from .deepseek_client import call_deepseek, call_deepseek_stream
from .sse import should_stream, sse_pack, sse_response
from .store import get_conv, set_conv, append_history

DEFAULT_KB_INDEX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "kb_index"))

# 只清理形如  \n<br/>\n\n / \r\n<br />\r\n\r\n 的块；大小写不敏感
# _BR_BLOCK = re.compile(r"(?:\r?\n)?<br\s*/?>\s*\r?\n\r?\n", re.IGNORECASE)
_BR_BLOCK = re.compile(r"(?:\r?\n)?<br\s*/?>\s*(?:\r?\n){2}", re.IGNORECASE)

# 将替换目标从 " " 改为 "\n"
_BR_REPLACEMENT = "\n- "   # 若要空一行就用 "\n\n"

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

def build_full_system_prompt(mingpan: Dict[str, Any], kb_passages: List[str]) -> str:
    fp_text = _format_four_pillars(mingpan["four_pillars"])
    dy_text = _format_dayun(mingpan["dayun"])
    composed = SYSTEM_PROMPT.replace("{FOUR_PILLARS}", fp_text).replace("{DAYUN}", dy_text)
    if kb_passages:
        kb_block = "\n\n".join(kb_passages[:3])
        composed += f"\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"
    return _append_md_rules(composed)

def start_chat(paipan: Dict[str, Any], kb_index_dir: Optional[str], kb_topk: int, request: Request):
    # RAG for start
    kb_passages: List[str] = []
    if kb_topk:
        kb_passages = retrieve_kb("开场上下文", os.path.abspath(kb_index_dir or DEFAULT_KB_INDEX), k=min(3, kb_topk))

    composed = build_full_system_prompt(
        {"four_pillars": paipan["four_pillars"], "dayun": paipan["dayun"]},
        kb_passages
    )

    cid = f"conv_{uuid.uuid4().hex[:8]}"
    set_conv(cid, {"pinned": composed, "history": [], "kb_index_dir": os.path.abspath(kb_index_dir or DEFAULT_KB_INDEX)})

    opening_user_msg = (
        "请基于以上命盘做一份通用且全面的解读，条理清晰，"
        "涵盖性格亮点、适合方向、注意点与三年内重点建议。"
        "结尾提醒：以上内容由传统文化AI生成，仅供娱乐参考。"
    )

    messages = [
        {"role": "system", "content": composed},
        {"role": "user", "content": opening_user_msg}
    ]

    # 流式
    if should_stream(request):
        def gen() -> Iterator[bytes]:
            full: List[str] = []
            try:
                yield sse_pack(json.dumps({"meta": {"conversation_id": cid}}, ensure_ascii=False))
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
                append_history(cid, "user", opening_user_msg)
                append_history(cid, "assistant", final)
        return sse_response(gen)

    # 一次性
    reply = normalize_markdown(call_deepseek(messages)).strip()
    reply = _scrub_br_block(reply)                             # ← 新增兜底替换
    reply = _collapse_double_newlines(reply)                    # ← 新增：把 \n\n 压成 \n
    reply = _third_sub(reply)                                  # ← 新增：把 \n\n 压成 \n
    append_history(cid, "user", opening_user_msg)
    append_history(cid, "assistant", reply)
    return cid, reply

def send_chat(conversation_id: str, message: str, request: Request):
    conv = get_conv(conversation_id)
    if not conv:
        raise ValueError("会话不存在，请先 /chat/start")

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
                    yield sse_pack(json.dumps({"text": clean, "replace": True}, ensure_ascii=False))
                yield sse_pack("[DONE]")
            except Exception as e:
                yield sse_pack(f"[ERROR]{str(e)}")
            finally:
                final = normalize_markdown("".join(full)).strip()
                append_history(conversation_id, "user", message)
                append_history(conversation_id, "assistant", final)
        return sse_response(gen)

    reply = normalize_markdown(call_deepseek(messages))
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
