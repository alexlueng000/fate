# app/schemas/message_rating.py
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal, Optional, Dict, Any


RatingType = Literal["up", "down"]
RatingReason = Literal["inaccurate", "irrelevant", "unclear", "inappropriate", "other"]


class MessageRatingCreate(BaseModel):
    """创建消息评价请求"""
    rating_type: RatingType = Field(..., description="评价类型：up=点赞, down=点踩")
    reason: Optional[RatingReason] = Field(None, description="点踩原因：仅在rating_type=down时需要")
    custom_reason: Optional[str] = Field(None, description="自定义理由：当reason=other时提供，最少15字，最多500字")
    paipan_data: Optional[Dict[str, Any]] = Field(None, description="命盘数据：点踩时保存用于后续分析")


class MessageRatingResp(BaseModel):
    """消息评价响应"""
    id: int
    rating_type: str
    reason: Optional[str]
    created_at: datetime


class UserRatingResp(BaseModel):
    """用户对指定消息的评价状态"""
    message_id: int
    user_rating: Optional[MessageRatingResp]


class MessageRatingOkResp(BaseModel):
    """操作成功响应"""
    ok: bool
