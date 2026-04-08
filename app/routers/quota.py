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


@router.get("/me", response_model=QuotaResponse)
def get_my_quota(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuotaResponse:
    """
    获取当前用户的 quota 信息
    """
    quota = QuotaService.get_or_create_quota(db, current_user.id, "chat")

    return QuotaResponse(
        total=quota.total_quota,
        used=quota.used_quota,
        remaining=quota.remaining,
        is_unlimited=quota.is_unlimited,
    )
