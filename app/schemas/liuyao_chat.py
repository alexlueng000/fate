from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LiuyaoChatSendReq(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=4000)


class LiuyaoChatQuickReq(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=64)
    kind: Literal["character", "timing"]


class LiuyaoChatRegenerateReq(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=64)


class LiuyaoChatReply(BaseModel):
    conversation_id: str
    reply: str
