# app/routers/quota.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services.quota import QuotaService

router = APIRouter(prefix="/quota", tags=["quota"])


class QuotaResponse(BaseModel):
    total: int
    used: int
    remaining: int
    is_unlimited: bool


class QuotaItem(BaseModel):
    """单一类型的配额（chat / liuyao_chat 等）。"""
    quota_type: str
    total: int
    used: int
    remaining: int
    is_unlimited: bool


class MyQuotasResponse(BaseModel):
    """当前用户全部配额。前端读取后按类型展示。"""
    chat: QuotaItem
    liuyao_chat: QuotaItem


def _to_item(quota_type: str, quota) -> QuotaItem:
    return QuotaItem(
        quota_type=quota_type,
        total=quota.total_quota,
        used=quota.used_quota,
        remaining=quota.remaining,
        is_unlimited=quota.is_unlimited,
    )


@router.get("/me", response_model=QuotaResponse)
def get_my_quota(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuotaResponse:
    """
    获取当前用户的 chat 配额（保持兼容；新代码请使用 /quota/me/all）。
    """
    quota = QuotaService.get_or_create_quota(db, current_user.id, "chat")

    return QuotaResponse(
        total=quota.total_quota,
        used=quota.used_quota,
        remaining=quota.remaining,
        is_unlimited=quota.is_unlimited,
    )


@router.get("/me/all", response_model=MyQuotasResponse)
def get_my_quotas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MyQuotasResponse:
    """
    返回当前用户的全部业务配额：八字（chat）+ 六爻（liuyao_chat）。
    用于前端在 chat / panel / liuyao 页头展示剩余次数。
    """
    chat = QuotaService.get_or_create_quota(db, current_user.id, "chat")
    liuyao = QuotaService.get_or_create_quota(db, current_user.id, "liuyao_chat")

    return MyQuotasResponse(
        chat=_to_item("chat", chat),
        liuyao_chat=_to_item("liuyao_chat", liuyao),
    )
