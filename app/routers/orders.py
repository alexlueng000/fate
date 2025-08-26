# app/routers/orders.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db_tx
from app.deps import get_current_user
from app.schemas import OrderCreate, OrderOut
from app.models import User, Order
from app.services.orders import create_order_by_code, get_orders_by_user, get_order_by_id_for_user

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    body: OrderCreate,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user),
) -> OrderOut:
    """
    创建订单：
    - 不传 product_code 则自动使用默认单品（settings.single_product_code）
    - 返回订单基础信息（状态为 CREATED）
    """
    try:
        order: Order = create_order_by_code(
            db, user=current_user, product_code=body.product_code, active_only=True
        )
        return order
    except ValueError as e:
        # 商品不存在或未上架
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/my", response_model=list[OrderOut])
def list_my_orders(
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user),
) -> list[OrderOut]:
    """
    查询我的订单列表（按创建时间倒序，默认最多 50 条）。
    """
    return get_orders_by_user(db, user=current_user, limit=50, offset=0)


@router.get("/{order_id}", response_model=OrderOut)
def get_my_order(
    order_id: int,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user),
) -> OrderOut:
    """
    获取我的某一笔订单详情。
    —— 含“越权保护”：只能读取属于自己的订单。
    """
    order = get_order_by_id_for_user(db, user=current_user, order_id=order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order
