# app/routers/user_stats.py
"""
用户统计 API
- 获取当前用户的配额信息
- 获取当前用户的使用统计
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.quota import QuotaService


router = APIRouter(prefix="/user", tags=["user-stats"])


# ==================== Pydantic 模型 ====================

class QuotaInfo(BaseModel):
    type: str
    total: int
    used: int
    remaining: int
    is_unlimited: bool
    period: str
    source: str


class UsageInfo(BaseModel):
    today_count: int
    total_count: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int


class UserStatsResponse(BaseModel):
    quotas: List[QuotaInfo]
    usage: UsageInfo


class QuotaResponse(BaseModel):
    type: str
    total: int
    used: int
    remaining: int
    is_unlimited: bool
    period: str
    source: str


# ==================== API 端点 ====================

@router.get("/quota", response_model=QuotaResponse)
def get_my_quota(
    quota_type: str = "chat",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> QuotaResponse:
    """
    获取当前用户的配额信息
    """
    quota = QuotaService.get_or_create_quota(db, current_user.id, quota_type)
    return QuotaResponse(
        type=quota.quota_type,
        total=quota.total_quota,
        used=quota.used_quota,
        remaining=quota.remaining,
        is_unlimited=quota.is_unlimited,
        period=quota.period,
        source=quota.source,
    )


@router.get("/stats", response_model=UserStatsResponse)
def get_my_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> UserStatsResponse:
    """
    获取当前用户的完整统计信息
    """
    stats = QuotaService.get_user_stats(db, current_user.id)
    return UserStatsResponse(
        quotas=[QuotaInfo(**q) for q in stats["quotas"]],
        usage=UsageInfo(**stats["usage"]),
    )
