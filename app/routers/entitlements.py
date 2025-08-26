# app/routers/entitlements.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import EntitlementOut
from app.services import entitlements as ent_service

router = APIRouter(prefix="/entitlements", tags=["entitlements"])


@router.get("/my", response_model=list[EntitlementOut])
def list_my_entitlements(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user),
) -> list[EntitlementOut]:
    """查询当前用户的全部权益。"""
    return ent_service.list_by_user(db, user=current_user)


@router.get("/{product_code}", response_model=bool)
def has_entitlement(
    product_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> bool:
    """检查当前用户是否已拥有某个功能（按 product_code）。"""
    return ent_service.has(db, user=current_user, product_code=product_code)
