import os
import sys
import uuid
import json
import requests

from typing import Optional, List, Dict, Any, Iterator
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..utils.prompts import SYSTEM_PROMPT
from kb_rag_mult import load_index, EmbeddingBackend, top_k_cosine

from dotenv import load_dotenv
load_dotenv()

# === 让 Python 能找到两级目录外的 kb_rag_mult.py ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SYS_KB_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
if SYS_KB_ROOT not in sys.path:
    sys.path.insert(0, SYS_KB_ROOT)

system_prompt = SYSTEM_PROMPT

# ====== 环境变量里的 Key，别硬编码 ======
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL   = "deepseek-chat"

# ====== 会话内存表（demo）======
# 生产请换 DB：表结构 {conversation_id, pinned_prompt, history(json), created_at,...}
_CONV: Dict[str, Dict[str, Any]] = {}

# ====== 默认知识库索引目录（按你的项目结构来）======
DEFAULT_KB_INDEX = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "kb_index"))

# ====== 工具：判断是否走流式 ======
def _should_stream(req: Request) -> bool:
    """
    当请求 Accept 包含 text/event-stream 或 query 参数 stream=1/true 时，走 SSE。
    """
    accept = (req.headers.get("accept") or "").lower()
    if "text/event-stream" in accept:
        return True
    q = req.query_params.get("stream")
    if q and q.lower() in ("1", "true", "yes", "y"):
        return True
    return False

# ====== 格式化工具 ======
def format_four_pillars(fp: Dict[str, List[str]]) -> str:
    return (
        f"年柱: {''.join(fp['year'])}\n"
        f"月柱: {''.join(fp['month'])}\n"
        f"日柱: {''.join(fp['day'])}\n"
        f"时柱: {''.join(fp['hour'])}"
    )

def format_dayun(dy: List[Dict]) -> str:
    lines = []
    for item in dy:
        pillar = "".join(item["pillar"])
        lines.append(f"- 起始年龄 {item['age']}，起运年 {item['start_year']}，大运 {pillar}")
    return "\n".join(lines)

def retrieve_kb(query: str, index_dir: str, k: int = 3) -> List[str]:
    """从本地知识库取 Top-k 片段，返回带文件名的片段文本列表"""
    chunks, sources, embs, meta = load_index(index_dir)
    eb = EmbeddingBackend(force_backend=meta.get("backend", "st"))
    if meta.get("backend") == "tfidf" and eb.vectorizer is not None:
        eb.vectorizer.fit(chunks)
    q_vec = eb.transform([query])
    idxs = top_k_cosine(q_vec, embs, k=k)
    passages = []
    for i in idxs:
        file_ = sources[i]["file"] if i < len(sources) else "unknown"
        passages.append(f"【{file_}】{chunks[i]}")
    return passages

def _append_md_rules(prompt: str) -> str:
    """在提示词最后追加 Markdown 规范，减少标题/列表串行问题"""
    rules = (
        "\n\n【输出格式要求】\n"
        "- 全文使用 Markdown。\n"
        "- 标题只能使用 `###`（一级）、`####`（二级），禁止使用其他层级。\n"
        "- 标题写法：`### 标题`（# 后必须有空格），标题前后必须空一行。\n"
        "- 小节标题示例：`#### 一、小节名`（`####` 后必须有空格）。\n"
        "- 段落与段落之间必须空一行，避免标题和正文、标题和标题直接连在一起。\n"
        "- 列表项必须独立换行，使用 `- ` 或 `1. `，不要把多个要点写在同一行。\n"
        "- 禁止使用分割线（---、***）、引用符号 `>`、斜体、粗体；如需强调请用全角符号【】。\n"
        "- 禁止复杂嵌套（例如列表中套标题、表格等）。\n"
        "- 输出应遵循最基础、最兼容的 Markdown 规范，确保前端组件能正确解析。\n"
    )
    return f"{prompt}\n{rules}"

def build_full_system_prompt(mingpan: Dict[str, Any], kb_passages: List[str]) -> str:
    """把四柱/大运 + 知识库片段一起塞到 system prompt，并追加 Markdown 规范"""
    fp_text = format_four_pillars(mingpan["four_pillars"])
    dy_text = format_dayun(mingpan["dayun"])
    composed = system_prompt.replace("{FOUR_PILLARS}", fp_text).replace("{DAYUN}", dy_text)
    if kb_passages:
        kb_block = "\n\n".join(kb_passages[:3])  # 控制长度，最多取3段
        composed += f"\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"
    composed = _append_md_rules(composed)
    # print("最终的提示词: ", composed)
    return composed

# ====== 调用 DeepSeek（一次性）======
def call_deepseek(messages: List[Dict[str, str]]) -> str:
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800
    }
    r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]

# ====== 调用 DeepSeek（流式，OpenAI 兼容）======
def call_deepseek_stream(messages: List[Dict[str, str]]) -> Iterator[str]:
    """
    逐段产出文本增量。
    兼容 OpenAI Chat Completions 的流式格式：每行以 'data: {...json...}'。
    """
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800,
        "stream": True,
    }
    with requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, stream=True, timeout=300) as r:
        r.raise_for_status()
        for raw_line in r.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    obj = json.loads(data)
                except Exception:
                    # 上游偶发非 JSON 内容，直接透传
                    yield data
                    continue
                delta = obj.get("choices", [{}])[0].get("delta", {})
                if "content" in delta and delta["content"]:
                    yield delta["content"]

# ====== SSE 包装 ======
def _sse_pack(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")

# ====== 请求/响应模型 ======
class PaipanPayload(BaseModel):
    four_pillars: Dict[str, List[str]]
    dayun: List[Dict[str, Any]]

class ChatStartReq(BaseModel):
    paipan: PaipanPayload
    kb_index_dir: Optional[str] = None
    kb_topk: int = 0
    note: Optional[str] = None

class ChatStartResp(BaseModel):
    conversation_id: str
    reply: str

class ChatSendReq(BaseModel):
    conversation_id: str = Field(..., description="由 /chat/start 返回")
    message: str

class ChatSendResp(BaseModel):
    conversation_id: str
    reply: str

class ChatRegenerateReq(BaseModel):
    conversation_id: str = Field(..., description="目标会话ID")

# ====== 路由 ======
router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/start")
def chat_start(req: ChatStartReq, request: Request, db: Session = Depends(get_db)):
    """
    支持 JSON 或 SSE：
    - Accept: text/event-stream 或 ?stream=1 → SSE 流式输出（首条会发送 meta：conversation_id）
    - 其他 → JSON 一次性返回
    """
    kb_dir = os.path.abspath(req.kb_index_dir or DEFAULT_KB_INDEX)
    kb_passages: List[str] = []
    if req.kb_topk and os.path.exists(os.path.join(kb_dir, "chunks.json")):
        try:
            kb_passages = retrieve_kb("开场上下文", kb_dir, k=min(3, req.kb_topk))
        except Exception:
            kb_passages = []

    # 固定的 system prompt（内含命盘，必要时拼开场RAG）
    pinned = build_full_system_prompt(
        {"four_pillars": req.paipan.four_pillars, "dayun": req.paipan.dayun},
        kb_passages
    )

    cid = f"conv_{uuid.uuid4().hex[:8]}"
    _CONV[cid] = {
        "pinned": pinned,
        "history": [],
        "kb_index_dir": kb_dir,
    }

    opening_user_msg = (
        "请基于以上命盘做一份通用且全面的解读，条理清晰，"
        "涵盖性格亮点、适合方向、注意点与三年内重点建议。"
        "结尾提醒：以上内容由传统文化AI生成，仅供娱乐参考。"
    )

    # 为首轮也加RAG
    opening_kb_passages: List[str] = []
    if os.path.exists(os.path.join(kb_dir, "chunks.json")):
        try:
            opening_kb_passages = retrieve_kb(opening_user_msg, kb_dir, k=3)
        except Exception:
            opening_kb_passages = []

    composed = pinned
    if opening_kb_passages:
        kb_block = "\n\n".join(opening_kb_passages)
        composed = f"{composed}\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"

    print("最终的提示词: ", composed)

    messages = [
        {"role": "system", "content": composed},
        {"role": "user", "content": opening_user_msg}
    ]

    # --- 流式 ---
    if _should_stream(request):
        def gen() -> Iterator[bytes]:
            full_text = []
            try:
                # 1) 先发 meta（conversation_id）
                meta = {"meta": {"conversation_id": cid}}
                yield _sse_pack(json.dumps(meta, ensure_ascii=False))
                # 2) 再持续输出文本
                for delta in call_deepseek_stream(messages):
                    if delta:
                        full_text.append(delta)
                        # 尽量将小片段原样透传，前端再渲染 Markdown
                        yield _sse_pack(delta)
                # 3) 结束标记
                yield _sse_pack("[DONE]")
            except Exception as e:
                yield _sse_pack(f"[ERROR]{str(e)}")
            finally:
                # 写入历史
                final = "".join(full_text).strip()
                _CONV[cid]["history"].append({"role": "user", "content": opening_user_msg})
                _CONV[cid]["history"].append({"role": "assistant", "content": final})

        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Nginx 关闭缓冲
        }
        return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

    # --- 一次性 JSON ---
    try:
        first_reply = call_deepseek(messages)
        print("首轮回复: ", first_reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上游模型错误：{e}")

    _CONV[cid]["history"].append({"role": "user", "content": opening_user_msg})
    _CONV[cid]["history"].append({"role": "assistant", "content": first_reply})
    return ChatStartResp(conversation_id=cid, reply=first_reply)

@router.post("")
def chat_send(req: ChatSendReq, request: Request, db: Session = Depends(get_db)):
    """
    续聊：支持 JSON 或 SSE。
    前端只传 {conversation_id, message}
    服务端负责：取 pinned + （可选RAG）+ 近几轮历史 + 本轮 user，调用 DeepSeek
    """
    conv = _CONV.get(req.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在，请先 /chat/start")

    # RAG：根据本轮问题做 Top-k（可按需关闭/开启）
    kb_passages: List[str] = []
    kb_dir = conv.get("kb_index_dir") or DEFAULT_KB_INDEX
    if os.path.exists(os.path.join(kb_dir, "chunks.json")):
        try:
            kb_passages = retrieve_kb(req.message, kb_dir, k=3)
        except Exception:
            kb_passages = []

    composed = conv["pinned"]
    if kb_passages:
        kb_block = "\n\n".join(kb_passages)
        composed = f"{composed}\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"

    print("最终的提示词: ", composed)

    # 组装 messages：pinned + 最近N + 本轮 user
    recentN = 10
    messages = [{"role": "system", "content": composed}]
    messages.extend(conv["history"][-recentN:])
    messages.append({"role": "user", "content": req.message})

    # --- 流式 ---
    if _should_stream(request):
        def gen() -> Iterator[bytes]:
            full_text = []
            try:
                # 也可以将会话ID作为 meta 发一条（前端当前已有 ID，但发一条更稳妥）
                meta = {"meta": {"conversation_id": req.conversation_id}}
                yield _sse_pack(json.dumps(meta, ensure_ascii=False))
                for delta in call_deepseek_stream(messages):
                    if delta:
                        full_text.append(delta)
                        yield _sse_pack(delta)
                yield _sse_pack("[DONE]")
            except Exception as e:
                yield _sse_pack(f"[ERROR]{str(e)}")
            finally:
                final = "".join(full_text).strip()
                conv["history"].append({"role": "user", "content": req.message})
                conv["history"].append({"role": "assistant", "content": final})

        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

    # --- 一次性 JSON ---
    try:
        reply = call_deepseek(messages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上游模型错误：{e}")

    # 保存历史
    conv["history"].append({"role": "user", "content": req.message})
    conv["history"].append({"role": "assistant", "content": reply})

    return ChatSendResp(conversation_id=req.conversation_id, reply=reply)

@router.post("/regenerate", response_model=ChatSendResp)
def chat_regenerate(req: ChatRegenerateReq, db: Session = Depends(get_db)):
    """
    重新生成上一条 Assistant 回复（一次性返回）
    """
    conv = _CONV.get(req.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在，请先 /chat/start")

    history = conv.get("history", [])
    if not history:
        raise HTTPException(status_code=400, detail="历史为空，无法重生")

    if history[-1]["role"] != "assistant":
        raise HTTPException(status_code=400, detail="最后一条不是 assistant，无法重生")

    # 删除最后一条 assistant
    history.pop()

    # 最近 user
    last_user_msg = None
    for m in reversed(history):
        if m["role"] == "user":
            last_user_msg = m["content"]
            break
    if not last_user_msg:
        last_user_msg = "请基于以上上下文继续完善上一轮解读。"

    # RAG
    kb_passages: List[str] = []
    kb_dir = conv.get("kb_index_dir") or DEFAULT_KB_INDEX
    if os.path.exists(os.path.join(kb_dir, "chunks.json")):
        try:
            kb_passages = retrieve_kb(last_user_msg, kb_dir, k=3)
        except Exception:
            kb_passages = []

    composed = conv["pinned"]
    if kb_passages:
        kb_block = "\n\n".join(kb_passages)
        composed = f"{composed}\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"

    # 组装 messages：pinned + 修剪后的最近N条历史（此时末尾应是 user）
    recentN = 10
    trimmed_history = history[-recentN:]
    messages = [{"role": "system", "content": composed}]
    messages.extend(trimmed_history)

    # 调用模型
    try:
        reply = call_deepseek(messages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上游模型错误：{e}")

    history.append({"role": "assistant", "content": reply})
    return ChatSendResp(conversation_id=req.conversation_id, reply=reply)
