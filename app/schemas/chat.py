from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any


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
    gender: str = Field(..., description="性别：男/女")
    four_pillars: Dict[str, List[str]]
    dayun: List[Dict[str, Any]]
    solar_date: Optional[str] = Field(None, description="排盘使用的公历日期时间（可能仅经度修正，不含均时差），YYYY-MM-DD HH:MM:SS")

class ChatStartReq(BaseModel):
    personal_report: bool = False
    paipan: Optional[PaipanPayload] = None
    guest_analysis_public_id: Optional[str] = None
    kb_index_dir: Optional[str] = None
    kb_topk: int = Field(0, ge=0, description="报告每个主题检索的片段数，0 使用自动值 3；最多每主题 3 条")
    note: Optional[str] = None
    task_context: Optional[Dict[str, Any]] = None

class ChatInitResp(BaseModel):
    conversation_id: str

class ChatStartResp(BaseModel):
    conversation_id: str
    reply: str

class ChatSendReq(BaseModel):
    request_key: Optional[str] = Field(None, pattern=r'^[a-f0-9]{32}$')
    conversation_id: str = Field(..., description="由 /chat/start 返回")
    message: str
    display_message: Optional[str] = Field(None, description="展示/入库用的用户消息，避免保存内部快捷 prompt")
    task_context: Optional[Dict[str, Any]] = None

class ChatSendResp(BaseModel):
    conversation_id: str
    reply: str
    message_id: Optional[int] = None

class ChatRegenerateReq(BaseModel):
    conversation_id: str = Field(..., description="目标会话ID")
    expected_message_id: Optional[int] = None

class ChatClearReq(BaseModel):
    conversation_id: str = Field(..., description="目标会话ID")

class ChatOkResp(BaseModel):
    ok: bool
    conversation_id: str

class ChatSimplifyReq(BaseModel):
    message_content: str
    conversation_id: Optional[str] = None
