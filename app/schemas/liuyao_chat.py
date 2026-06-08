from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class LiuyaoChatStartReq(BaseModel):
    task_context: Optional[Dict[str, Any]] = None


class LiuyaoChatSendReq(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=4000)


class LiuyaoChatQuickReq(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=64)
    prompt: str = Field(..., min_length=1, max_length=4000)


class LiuyaoChatRegenerateReq(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=64)


class LiuyaoChatReply(BaseModel):
    conversation_id: str
    reply: str
