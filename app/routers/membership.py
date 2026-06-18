from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import MembershipMeOut, ProductDetailOut
from app.services.membership_service import get_active_membership, has_video_access
from app.services.products import list_products
from app.services.quota import QuotaService

router = APIRouter(prefix="/membership", tags=["membership"])


@router.get("/plans", response_model=list[ProductDetailOut])
def get_membership_plans(db: Session = Depends(get_db)) -> list[ProductDetailOut]:
    products = list_products(db, active_only=True)
    return [p for p in products if p.kind == "subscription"]


@router.get("/topup-packages", response_model=list[ProductDetailOut])
def get_topup_packages(db: Session = Depends(get_db)) -> list[ProductDetailOut]:
    products = list_products(db, active_only=True)
    return [p for p in products if p.kind == "topup"]


@router.get("/me", response_model=MembershipMeOut)
def get_my_membership(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MembershipMeOut:
    membership = get_active_membership(db, current_user.id)
    return MembershipMeOut(
        active=membership is not None,
        membership=membership,
        video_access=has_video_access(db, current_user.id),
    )


@router.get("/usage")
def get_my_membership_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return QuotaService.get_user_stats(db, current_user.id)
