import os
import sys
import uuid
import requests

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
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

def build_full_system_prompt(mingpan: Dict[str, Any], kb_passages: List[str]) -> str:
    """把四柱/大运 + 知识库片段一起塞到 system prompt"""
    fp_text = format_four_pillars(mingpan["four_pillars"])
    dy_text = format_dayun(mingpan["dayun"])
    # 你的 system_prompt 用的是 {{FOUR_PILLARS}}/{{DAYUN}}，这里替换为实际文本
    composed = system_prompt.replace("{FOUR_PILLARS}", fp_text).replace("{DAYUN}", dy_text)
    if kb_passages:
        kb_block = "\n\n".join(kb_passages[:3])  # 控制长度，最多取3段
        composed += f"\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"

    print("最终的提示词: ", composed)
    
    return composed

# ====== 调用 DeepSeek ======
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


# ====== 请求/响应模型 ======
class PaipanPayload(BaseModel):
    four_pillars: Dict[str, List[str]]
    dayun: List[Dict[str, Any]]

class ChatStartReq(BaseModel):
    paipan: PaipanPayload
    kb_index_dir: Optional[str] = None       # 可选，默认用 DEFAULT_KB_INDEX
    kb_topk: int = 0                         # 启动时要不要先拼 RAG 片段（通常 0）
    note: Optional[str] = None               # 备注（可忽略）

class ChatStartResp(BaseModel):
    conversation_id: str
    reply: str

class ChatSendReq(BaseModel):
    conversation_id: str = Field(..., description="由 /chat/start 返回")
    message: str

class ChatSendResp(BaseModel):
    conversation_id: str
    reply: str



# ====== 路由 ======
router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/start", response_model=ChatStartResp)
def chat_start(req: ChatStartReq, db: Session = Depends(get_db)):
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

    # ❗开场“通用解读”——固定的一句用户开场语
    opening_user_msg = "请基于以上命盘做一份通用且全面的解读，条理清晰，涵盖性格亮点、适合方向、注意点与三年内重点建议。结尾提醒：以上内容由传统文化AI生成，仅供娱乐参考。"

    # 如需为首轮也加RAG，可在此检索
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

    # 组装 messages 并调用一次 DeepSeek
    messages = [
        {"role": "system", "content": composed},
        {"role": "user", "content": opening_user_msg}
    ]
    try:
        first_reply = call_deepseek(messages)
        print("首轮回复: ", first_reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上游模型错误：{e}")

    # 写入历史（首轮）
    _CONV[cid]["history"].append({"role": "user", "content": opening_user_msg})
    _CONV[cid]["history"].append({"role": "assistant", "content": first_reply})

    return ChatStartResp(conversation_id=cid, reply=first_reply)


@router.post("", response_model=ChatSendResp)
def chat_send(req: ChatSendReq, db: Session = Depends(get_db)):
    """
    续聊：前端只传 {conversation_id, message}
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

    # 把当轮 RAG 片段拼到 pinned 后面（不修改原 pinned，只在本次 messages 使用）
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

    # 调用 DeepSeek
    try:
        reply = call_deepseek(messages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上游模型错误：{e}")

    # 保存历史
    conv["history"].append({"role": "user", "content": req.message})
    conv["history"].append({"role": "assistant", "content": reply})

    return ChatSendResp(conversation_id=req.conversation_id, reply=reply)