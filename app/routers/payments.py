# app/routers/payments.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db_tx
from app.deps import get_current_user
from app.schemas import PaymentPrepayCreate, PaymentOut
from app.services import payments as pay_service
from app.services import orders as order_service
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
