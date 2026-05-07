# app/routers/payments.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db_tx
from app.deps import get_current_user
from app.schemas import (
    PaymentPrepayCreate,
    PaymentOut,
    SimulatePaymentIn,
    SimulatePaymentOut,
    QuotaSnapshot,
)
from app.services import payments as pay_service
from app.services import orders as order_service
from app.services.products import get_by_code, grant_product_quota
from app.services.quota import QuotaService
from app.models import User, Order

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/prepay", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_prepay(
    body: PaymentPrepayCreate,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user),
) -> PaymentOut:
    """
    创建预支付记录（开发态）：
    - order 必须属于当前用户，且状态为 CREATED
    - channel: WECHAT_JSAPI / WECHAT_NATIVE
    - 返回预支付参数（开发态生成一个占位 prepay_id）
    """
    # 验证订单归属与状态
    order: Order | None = order_service.get_order_by_id_for_user(
        db, user=current_user, order_id=body.order_id
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    if order.status != "CREATED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order status must be CREATED, got {order.status}",
        )

    try:
        payment = pay_service.create_prepay(
            db, order=order, channel=body.channel.value
        )
        return payment
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/simulate", response_model=SimulatePaymentOut, status_code=status.HTTP_201_CREATED)
def simulate_payment(
    body: SimulatePaymentIn,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user),
) -> SimulatePaymentOut:
    """
    模拟支付（开发/演示用）：
    - 直接根据 product_code 创建订单 → 标记 PAID → 发放配额
    - 不走真实微信/支付宝渠道；transaction_id 形如 sim_<order_id>
    - 任意登录用户均可调用（生产环境收紧策略请见 §5b）
    """
    product = get_by_code(db, body.product_code, active_only=True)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在或已下架")

    # 1) 建单
    order = order_service._create_order(db, user=current_user, product=product)  # noqa: SLF001

    # 2) 标记成功（mark_success 内部会自动补一条 Payment 记录，channel=UNKNOWN）
    pay_service.mark_success(
        db,
        order=order,
        transaction_id=f"sim_{order.id}",
        raw="simulate",
    )

    # 3) 发放套餐配额
    granted = grant_product_quota(
        db,
        user_id=current_user.id,
        product=product,
        source="simulate",
    )

    # 4) 返回最新配额快照
    stats = QuotaService.get_user_stats(db, current_user.id)
    quotas = [QuotaSnapshot(**q) for q in stats.get("quotas", [])]

    return SimulatePaymentOut(
        order_id=order.id,
        product_code=product.code,
        granted=granted,
        quotas=quotas,
    )
