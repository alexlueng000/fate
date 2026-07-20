from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MembershipGrant, Order, Product, QuotaLedger, UserMembership
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

    if order:
        existing_grant = db.execute(
            select(MembershipGrant).where(MembershipGrant.order_id == order.id)
        ).scalars().first()
        if existing_grant:
            membership = db.execute(
                select(UserMembership)
                .where(
                    UserMembership.user_id == user_id,
                    UserMembership.product_id == product.id,
                )
                .order_by(UserMembership.current_period_end.desc())
                .limit(1)
            ).scalars().first()
            if membership:
                return membership
            raise RuntimeError(
                f"Membership grant exists without membership for order {order.id}"
            )

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
        grant_start = membership.current_period_end
        grant_end = grant_start + delta
        membership.status = "active"
        membership.current_period_start = min(membership.current_period_start, now)
        membership.current_period_end = grant_end
        membership.order_id = order.id if order else membership.order_id
        membership.cancelled_at = None
        if order:
            db.add(
                MembershipGrant(
                    user_id=user_id,
                    order_id=order.id,
                    product_id=product.id,
                    starts_at=grant_start,
                    ends_at=grant_end,
                    status="ACTIVE",
                )
            )
            db.flush()
        return membership

    grant_start = now
    grant_end = now + delta
    membership = UserMembership(
        user_id=user_id,
        product_id=product.id,
        order_id=order.id if order else None,
        status="active",
        current_period_start=grant_start,
        current_period_end=grant_end,
        auto_renew=False,
    )
    db.add(membership)
    db.flush()
    if order:
        db.add(
            MembershipGrant(
                user_id=user_id,
                order_id=order.id,
                product_id=product.id,
                starts_at=grant_start,
                ends_at=grant_end,
                status="ACTIVE",
            )
        )
        db.flush()
    return membership


def grant_product_entitlements(
    db: Session,
    *,
    user_id: int,
    product: Product,
    order: Optional[Order] = None,
    source: str = "purchase",
) -> dict[str, int]:
    requested: dict[str, int] = {}

    for grant in product.grants:
        if grant.amount <= 0:
            continue
        requested[grant.quota_type] = requested.get(grant.quota_type, 0) + grant.amount

    if not requested:
        if product.bazi_quota and product.bazi_quota > 0:
            requested["chat"] = product.bazi_quota

        if product.liuyao_quota and product.liuyao_quota > 0:
            requested["liuyao_chat"] = product.liuyao_quota

        if not requested and product.quota_amount and product.quota_amount > 0:
            requested["chat"] = product.quota_amount

    granted: dict[str, int] = {}
    for quota_type, amount in requested.items():
        if order:
            idempotency_key = f"order:{order.id}:quota:{quota_type}:grant"
            existing = db.execute(
                select(QuotaLedger).where(
                    QuotaLedger.idempotency_key == idempotency_key
                )
            ).scalars().first()
            if existing:
                continue

            db.add(
                QuotaLedger(
                    user_id=user_id,
                    quota_type=quota_type,
                    delta=amount,
                    event_type="PURCHASE_GRANT",
                    order_id=order.id,
                    idempotency_key=idempotency_key,
                    note=f"source={source}",
                )
            )

        QuotaService.add_quota(
            db,
            user_id,
            amount,
            quota_type,
            source,
            commit=order is None,
        )
        granted[quota_type] = amount

    if order:
        db.flush()

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
        order=order,
        source=source,
    )
    return membership, granted
