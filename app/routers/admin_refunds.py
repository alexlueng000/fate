from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db, get_db_tx
from app.deps import get_admin_user
from app.models import MembershipGrant, Order, Payment, Product, QuotaLedger, Refund, User
from app.schemas import AdminOrderListOut, AdminRefundCreate, RefundOut
from app.services.refunds import (
    RefundNotAllowed,
    RefundOrderNotFound,
    WeChatRefundError,
    create_full_refund_request,
    query_wechat_refund,
    submit_wechat_refund,
)

router = APIRouter(prefix="/admin", tags=["admin-refunds"])


@router.get("/orders", response_model=AdminOrderListOut)
def list_admin_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_status: str | None = Query(None),
    refund_status: str | None = Query(None),
    search: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
) -> AdminOrderListOut:
    stmt = (
        select(Order)
        .join(User, User.id == Order.user_id)
        .join(Product, Product.id == Order.product_id)
        .options(
            selectinload(Order.user),
            selectinload(Order.product).selectinload(Product.grants),
        )
    )
    count_stmt = select(func.count(Order.id)).join(
        User, User.id == Order.user_id
    ).join(Product, Product.id == Order.product_id)

    if refund_status:
        stmt = stmt.join(Refund, Refund.order_id == Order.id).where(
            Refund.status == refund_status
        ).distinct()
        count_stmt = select(func.count(func.distinct(Order.id))).join(
            User, User.id == Order.user_id
        ).join(Product, Product.id == Order.product_id).join(
            Refund, Refund.order_id == Order.id
        ).where(
            Refund.status == refund_status
        )
    if order_status:
        stmt = stmt.where(Order.status == order_status)
        count_stmt = count_stmt.where(Order.status == order_status)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        search_filter = or_(
            Order.out_trade_no.like(pattern),
            User.email.like(pattern),
            User.phone.like(pattern),
            User.nickname.like(pattern),
            Product.name.like(pattern),
            Product.code.like(pattern),
        )
        stmt = stmt.where(search_filter)
        count_stmt = count_stmt.where(search_filter)

    total = int(db.execute(count_stmt).scalar() or 0)
    orders = list(
        db.execute(
            stmt.order_by(Order.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars().all()
    )
    if not orders:
        return AdminOrderListOut(items=[], total=total, page=page, page_size=page_size)

    order_ids = [order.id for order in orders]
    payments = list(
        db.execute(
            select(Payment)
            .where(Payment.order_id.in_(order_ids))
            .order_by(Payment.id.desc())
        ).scalars().all()
    )
    refunds = list(
        db.execute(
            select(Refund)
            .where(Refund.order_id.in_(order_ids))
            .order_by(Refund.id.desc())
        ).scalars().all()
    )
    quota_trace_ids = set(
        db.execute(
            select(QuotaLedger.order_id).where(
                QuotaLedger.order_id.in_(order_ids),
                QuotaLedger.event_type == "PURCHASE_GRANT",
            )
        ).scalars().all()
    )
    membership_trace_ids = set(
        db.execute(
            select(MembershipGrant.order_id).where(
                MembershipGrant.order_id.in_(order_ids)
            )
        ).scalars().all()
    )

    latest_payment: dict[int, Payment] = {}
    for payment in payments:
        latest_payment.setdefault(payment.order_id, payment)
    latest_refund: dict[int, Refund] = {}
    for refund in refunds:
        latest_refund.setdefault(refund.order_id, refund)

    items = []
    for order in orders:
        payment = latest_payment.get(order.id)
        refund = latest_refund.get(order.id)
        expects_trace = order.product.kind == "subscription" or any(
            amount and amount > 0
            for amount in (
                order.product.bazi_quota,
                order.product.liuyao_quota,
                order.product.quota_amount,
            )
        ) or any(grant.amount > 0 for grant in order.product.grants)
        has_trace = order.id in quota_trace_ids or order.id in membership_trace_ids
        entitlement_trace = (
            "READY" if has_trace else "MISSING" if expects_trace else "NOT_REQUIRED"
        )
        items.append(
            {
                "id": order.id,
                "user_id": order.user_id,
                "user_email": order.user.email,
                "user_phone": order.user.phone,
                "user_nickname": order.user.nickname,
                "product_id": order.product_id,
                "product_code": order.product.code,
                "product_name": order.product.name,
                "product_kind": order.product.kind,
                "amount_cents": order.amount_cents,
                "currency": order.currency,
                "status": order.status,
                "out_trade_no": order.out_trade_no,
                "payment_channel": payment.channel if payment else None,
                "transaction_id": payment.transaction_id if payment else None,
                "entitlement_trace": entitlement_trace,
                "refund": refund,
                "created_at": order.created_at,
            }
        )

    return AdminOrderListOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/orders/{order_id}/refund",
    response_model=RefundOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_order_refund(
    order_id: int,
    body: AdminRefundCreate,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
) -> RefundOut:
    """Create an idempotent local full-refund request for an administrator."""

    try:
        refund = create_full_refund_request(
            db,
            order_id=order_id,
            requested_by=admin.id,
            reason=body.reason,
        )
        # Persist the stable out_refund_no before making an external request.
        db.commit()
        db.refresh(refund)
        refund = submit_wechat_refund(db, refund=refund)
        db.commit()
        db.refresh(refund)
        return refund
    except RefundOrderNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except RefundNotAllowed as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except WeChatRefundError as exc:
        # Preserve failure details so the same out_refund_no can be retried safely.
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc


@router.post(
    "/refunds/{refund_id}/sync",
    response_model=RefundOut,
)
def sync_order_refund(
    refund_id: int,
    db: Session = Depends(get_db_tx),
    _admin: User = Depends(get_admin_user),
) -> RefundOut:
    refund = db.execute(
        select(Refund).where(Refund.id == refund_id).with_for_update()
    ).scalars().first()
    if not refund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="退款单不存在"
        )

    try:
        return query_wechat_refund(db, refund=refund)
    except WeChatRefundError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
