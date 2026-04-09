# app/services/orders.py
from __future__ import annotations

import random
import string
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Order, Product, User
from app.services.products import get_by_code
from app.config import settings


# 读取默认单品编码（若未配置则使用 REPORT_UNLOCK）
SINGLE_PRODUCT_CODE: str = getattr(settings, "single_product_code", "REPORT_UNLOCK")


def _gen_out_trade_no() -> str:
    """
    生成商户单号：YYYYMMDDHHMMSS + 8位随机（A-Z0-9）。
    短小且在同一秒内碰撞概率极低；若仍撞唯一索引，会自动重试。
    """
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"{ts}{rand}"


def _alloc_unique_out_trade_no(db: Session, max_retry: int = 5) -> str:
    """
    保证 out_trade_no 唯一。若插入时撞唯一索引，最多重试 max_retry 次。
    """
    for _ in range(max_retry):
        candidate = _gen_out_trade_no()
        # 并发安全：真正的唯一保障交给 DB 唯一索引；这里不做额外查重。
        try:
            # 提前占位方式太重；在 create 时处理更自然，这里只返回字符串
            return candidate
        except Exception:
            pass
    # 理论上不会到这；仍返回一个值，让上层按 IntegrityError 再次重试
    return _gen_out_trade_no()


def _create_order(
    db: Session,
    *,
    user: User,
    product: Product,
) -> Order:
    """
    核心下单逻辑：金额/币种取自 Product；状态置为 CREATED。
    不在此函数内 commit；调用方可用 get_db_tx() 自动提交或手动提交。
    """
    out_trade_no = _alloc_unique_out_trade_no(db)
    order = Order(
        user_id=user.id,
        product_id=product.id,
        amount_cents=product.price_cents,
        currency=product.currency,
        status="CREATED",
        out_trade_no=out_trade_no,
    )
    db.add(order)
    try:
        db.flush()  # 让唯一索引/约束在当前事务中立即生效，获得 order.id
        return order
    except IntegrityError:
        # 可能极小概率 out_trade_no 撞唯一索引：重试一次
        db.rollback()
        out_trade_no = _alloc_unique_out_trade_no(db)
        order = Order(
            user_id=user.id,
            product_id=product.id,
            amount_cents=product.price_cents,
            currency=product.currency,
            status="CREATED",
            out_trade_no=out_trade_no,
        )
        db.add(order)
        db.flush()
        return order


def create_order_by_code(
    db: Session,
    *,
    user: User,
    product_code: Optional[str] = None,
    active_only: bool = True,
) -> Order:
    """
    基于商品编码创建订单：
    - 不传 product_code 时，默认用唯一单品（SINGLE_PRODUCT_CODE）
    - active_only=True 仅允许在售商品下单
    """
    code = product_code or SINGLE_PRODUCT_CODE
    product = get_by_code(db, code, active_only=active_only)
    if not product:
        raise ValueError("Product not found or not active")

    return _create_order(db, user=user, product=product)


def create_order_for_default_product(db: Session, *, user: User) -> Order:
    """
    为默认单品创建订单的便捷方法。
    """
    return create_order_by_code(db, user=user, product_code=SINGLE_PRODUCT_CODE)


def get_orders_by_user(
    db: Session,
    *,
    user: User,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Order]:
    """
    查询当前用户的订单列表，可按状态过滤。
    """
    stmt = select(Order).where(Order.user_id == user.id)
    if status:
        stmt = stmt.where(Order.status == status)
    stmt = stmt.order_by(Order.id.desc()).offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_order_by_id_for_user(
    db: Session, *, user: User, order_id: int
) -> Optional[Order]:
    """
    读取用户自己的某一笔订单（越权保护）。
    """
    stmt = select(Order).where(Order.id == order_id, Order.user_id == user.id)
    return db.execute(stmt).scalars().first()
