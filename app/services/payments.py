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


# ---------- 预支付 ----------
def create_prepay(
    db: Session,
    *,
    order: Order,
    channel: str,  # WECHAT_JSAPI / WECHAT_NATIVE / ALIPAY_PC / ALIPAY_H5
) -> Payment:
    """
    创建预支付记录（PENDING）。
    - 开发态：生成占位 prepay_id；支付宝渠道额外填充 pay_url
    - 不在此函数内 commit；调用方用 get_db_tx() 提交
    """
    if order.status != "CREATED":
        raise ValueError("Order is not in CREATED status")

    prepay_id: Optional[str] = None
    pay_url: Optional[str] = None

    if channel in ("ALIPAY_PC", "ALIPAY_H5"):
        # 开发态：生成占位跳转 URL（生产环境替换为支付宝 SDK 返回的表单 URL）
        prepay_id = f"dev_alipay_{order.out_trade_no}"
        pay_url = f"https://openapi.alipaydev.com/gateway.do?dev_order={order.out_trade_no}"
    else:
        # WeChat（WECHAT_JSAPI / WECHAT_NATIVE）
        prepay_id = f"dev_prepay_{order.out_trade_no}"

    pay = Payment(
        order_id=order.id,
        channel=channel,
        prepay_id=prepay_id,
        pay_url=pay_url,
        status="PENDING",
        raw=None,
    )
    db.add(pay)
    db.flush()
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
    支付成功落账（幂等）：
    - 将最新 Payment 标记为 SUCCESS，写入 transaction_id/raw
    - 将订单状态置为 PAID（若当前仍为 CREATED）
    """
    latest = get_latest_payment_for_order(db, order.id)
    if not latest:
        latest = Payment(order_id=order.id, channel="UNKNOWN", status="PENDING")
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
    latest = get_latest_payment_for_order(db, order.id)
    if not latest:
        latest = Payment(order_id=order.id, channel="UNKNOWN", status="PENDING")
        db.add(latest)
        db.flush()

    latest.status = "FAIL"
    latest.raw = raw
    db.flush()
    return latest
