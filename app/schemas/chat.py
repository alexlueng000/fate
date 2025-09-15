from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal, Optional, List


MessageRole = Literal["user", "assistant", "system"]


class ConversationCreateReq(BaseModel):
    title: Optional[str] = Field(default="未命名会话")


class ConversationRenameReq(BaseModel):
    conversation_id: int
    title: str


class ConversationDeleteReq(BaseModel):
    conversation_id: int


class ConversationItem(BaseModel):
    id: int
    title: str
    updated_at: datetime


class ConversationListResp(BaseModel):
    items: List[ConversationItem]


class MessageItem(BaseModel):
    id: int
    role: MessageRole
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: Optional[int] = None
    created_at: datetime


class HistoryResp(BaseModel):
    conversation_id: int
    page: int
    size: int
    total: int
    items: List[MessageItem]


# === 排盘 ===
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