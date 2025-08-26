# app/services/payments.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, Payment


# ---------- 读取 ----------
def get_payment_by_id(db: Session, payment_id: int) -> Optional[Payment]:
    return db.get(Payment, payment_id)


def get_latest_payment_for_order(db: Session, order_id: int) -> Optional[Payment]:
    stmt = (
        select(Payment)
        .where(Payment.order_id == order_id)
        .order_by(Payment.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


# ---------- 预支付（开发态占位） ----------
def create_prepay(
    db: Session,
    *,
    order: Order,
    channel: str,  # "WECHAT_JSAPI" / "WECHAT_NATIVE"
) -> Payment:
    """
    创建一条预支付记录（PENDING）。
    - 仅允许对 status=CREATED 的订单创建预支付
    - 开发态：生成一个占位 prepay_id，真实对接时替换为微信返回值
    不在此函数内 commit；调用方用 get_db_tx() 提交。
    """
    if order.status != "CREATED":
        raise ValueError("Order is not in CREATED status")

    prepay_id = f"dev_prepay_{order.out_trade_no}"
    pay = Payment(
        order_id=order.id,
        channel=channel,
        prepay_id=prepay_id,
        status="PENDING",
        raw=None,
    )
    db.add(pay)
    db.flush()  # 分配 id
    return pay


# ---------- 标记成功/失败（回调用） ----------
def mark_success(
    db: Session,
    *,
    order: Order,
    transaction_id: str,
    raw: Optional[str] = None,
) -> Payment:
    """
    支付成功落账：
    - 将最新一条 Payment 标记为 SUCCESS，写入 transaction_id/raw
    - 将订单状态置为 PAID（若当前仍为 CREATED）
    - 幂等：若订单已是 PAID，则直接返回最新 Payment
    """
    latest = get_latest_payment_for_order(db, order.id)
    if not latest:
        # 没有预支付记录也允许直接落账（兜底）
        latest = Payment(order_id=order.id, channel="WECHAT_JSAPI", status="PENDING")
        db.add(latest)
        db.flush()

    latest.transaction_id = transaction_id
    latest.status = "SUCCESS"
    latest.raw = raw
    if order.status == "CREATED":
        order.status = "PAID"

    db.flush()
    return latest


def mark_fail(
    db: Session,
    *,
    order: Order,
    raw: Optional[str] = None,
) -> Payment:
    """
    支付失败落账：
    - 将最新一条 Payment 标记为 FAIL，记录 raw
    - 不修改订单状态（仍为 CREATED，可重试）
    """
    latest = get_latest_payment_for_order(db, order.id)
    if not latest:
        latest = Payment(order_id=order.id, channel="WECHAT_JSAPI", status="PENDING")
        db.add(latest)
        db.flush()

    latest.status = "FAIL"
    latest.raw = raw
    db.flush()
    return latest
