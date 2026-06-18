from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, Product, UserMembership
from app.services.quota import QuotaService


def _period_delta(product: Product) -> timedelta:
    if product.period == "yearly":
        return timedelta(days=365)
    return timedelta(days=30)


def get_active_membership(db: Session, user_id: int) -> Optional[UserMembership]:
    now = datetime.utcnow()
    stmt = (
        select(UserMembership)
        .where(
            UserMembership.user_id == user_id,
            UserMembership.status == "active",
            UserMembership.current_period_end > now,
        )
        .order_by(UserMembership.current_period_end.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def has_video_access(db: Session, user_id: int) -> bool:
    membership = get_active_membership(db, user_id)
    if not membership:
        return False

    features = membership.product.features or {}
    return bool(features.get("video_access", True))


def create_or_renew_membership_for_order(
    db: Session,
    *,
    user_id: int,
    product: Product,
    order: Optional[Order] = None,
) -> UserMembership:
    now = datetime.utcnow()
    delta = _period_delta(product)

    stmt = (
        select(UserMembership)
        .where(
            UserMembership.user_id == user_id,
            UserMembership.product_id == product.id,
            UserMembership.current_period_end > now,
        )
        .order_by(UserMembership.current_period_end.desc())
        .limit(1)
        .with_for_update()
    )
    membership = db.execute(stmt).scalars().first()

    if membership:
        membership.status = "active"
        membership.current_period_start = min(membership.current_period_start, now)
        membership.current_period_end = membership.current_period_end + delta
        membership.order_id = order.id if order else membership.order_id
        membership.cancelled_at = None
        return membership

    membership = UserMembership(
        user_id=user_id,
        product_id=product.id,
        order_id=order.id if order else None,
        status="active",
        current_period_start=now,
        current_period_end=now + delta,
        auto_renew=False,
    )
    db.add(membership)
    db.flush()
    return membership


def grant_product_entitlements(
    db: Session,
    *,
    user_id: int,
    product: Product,
    source: str = "purchase",
) -> dict[str, int]:
    granted: dict[str, int] = {}

    for grant in product.grants:
        if grant.amount <= 0:
            continue
        QuotaService.add_quota(db, user_id, grant.amount, grant.quota_type, source)
        granted[grant.quota_type] = granted.get(grant.quota_type, 0) + grant.amount

    if granted:
        return granted

    if product.bazi_quota and product.bazi_quota > 0:
        QuotaService.add_quota(db, user_id, product.bazi_quota, "chat", source)
        granted["chat"] = product.bazi_quota

    if product.liuyao_quota and product.liuyao_quota > 0:
        QuotaService.add_quota(db, user_id, product.liuyao_quota, "liuyao_chat", source)
        granted["liuyao_chat"] = product.liuyao_quota

    if not granted and product.quota_amount and product.quota_amount > 0:
        QuotaService.add_quota(db, user_id, product.quota_amount, "chat", source)
        granted["chat"] = product.quota_amount

    return granted


def apply_paid_product(
    db: Session,
    *,
    user_id: int,
    product: Product,
    order: Optional[Order] = None,
    source: str = "purchase",
) -> tuple[Optional[UserMembership], dict[str, int]]:
    membership = None
    if product.kind == "subscription":
        membership = create_or_renew_membership_for_order(
            db,
            user_id=user_id,
            product=product,
            order=order,
        )

    granted = grant_product_entitlements(
        db,
        user_id=user_id,
        product=product,
        source=source,
    )
    return membership, granted
