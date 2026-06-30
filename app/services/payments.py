# app/services/payments.py
from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding as asy_padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from app.config import settings
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


def _load_merchant_private_key() -> bytes:
    if settings.wechat_pay_private_key_pem:
        return settings.wechat_pay_private_key_pem.encode("utf-8")
    if settings.wechat_pay_private_key_path:
        with open(settings.wechat_pay_private_key_path, "rb") as f:
            return f.read()
    raise ValueError("WeChat merchant private key is not configured")


def _wechat_appid() -> str:
    appid = settings.wechat_pay_appid or settings.wx_appid
    if not appid:
        raise ValueError("WECHAT_PAY_APPID or WX_APPID is not configured")
    return appid


def _wechat_notify_url() -> str:
    if settings.wechat_pay_notify_url:
        return settings.wechat_pay_notify_url
    raise ValueError("WECHAT_PAY_NOTIFY_URL is not configured")


def _wechat_auth_header(method: str, url_path: str, body: str) -> str:
    if not settings.wechat_pay_mchid:
        raise ValueError("WECHAT_PAY_MCHID is not configured")
    if not settings.wechat_pay_merchant_serial_no:
        raise ValueError("WECHAT_PAY_MERCHANT_SERIAL_NO is not configured")

    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    message = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"

    private_key = load_pem_private_key(_load_merchant_private_key(), password=None)
    signature = private_key.sign(
        message.encode("utf-8"),
        asy_padding.PKCS1v15(),
        hashes.SHA256(),
    )
    signature_text = base64.b64encode(signature).decode("utf-8")

    return (
        'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{settings.wechat_pay_mchid}",'
        f'nonce_str="{nonce}",'
        f'timestamp="{timestamp}",'
        f'serial_no="{settings.wechat_pay_merchant_serial_no}",'
        f'signature="{signature_text}"'
    )


def create_wechat_native_prepay(db: Session, *, order: Order) -> Payment:
    """
    Create a WeChat Pay v3 Native prepay order and store the returned QR code URL.
    """
    if order.status != "CREATED":
        raise ValueError("Order is not in CREATED status")

    if settings.wechat_pay_mode != "prod":
        payment = Payment(
            order_id=order.id,
            channel="WECHAT_NATIVE",
            prepay_id=f"dev_native_{order.out_trade_no}",
            pay_url=f"weixin://wxpay/bizpayurl?pr=dev_{order.out_trade_no}",
            status="PENDING",
            raw=json.dumps({"mode": "dev", "out_trade_no": order.out_trade_no}, ensure_ascii=False),
        )
        db.add(payment)
        db.flush()
        return payment

    url_path = "/v3/pay/transactions/native"
    body_dict = {
        "appid": _wechat_appid(),
        "mchid": settings.wechat_pay_mchid,
        "description": order.product.name[:127],
        "out_trade_no": order.out_trade_no,
        "notify_url": _wechat_notify_url(),
        "amount": {
            "total": order.amount_cents,
            "currency": order.currency,
        },
    }
    body = json.dumps(body_dict, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Authorization": _wechat_auth_header("POST", url_path, body),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "fateinsight/1.0",
    }

    with httpx.Client(timeout=15) as client:
        response = client.post(
            f"https://api.mch.weixin.qq.com{url_path}",
            content=body.encode("utf-8"),
            headers=headers,
        )

    if response.status_code >= 400:
        raise ValueError(f"WeChat Native prepay failed: {response.text}")

    data = response.json()
    code_url = data.get("code_url")
    if not code_url:
        raise ValueError("WeChat Native prepay response missing code_url")

    payment = Payment(
        order_id=order.id,
        channel="WECHAT_NATIVE",
        prepay_id=None,
        pay_url=code_url,
        status="PENDING",
        raw=response.text,
    )
    db.add(payment)
    db.flush()
    return payment


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
