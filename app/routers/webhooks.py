# app/routers/webhooks.py
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db_tx
from app.models import WebhookLog, Order
from app.services import payments as pay_service
from app.services import entitlements as ent_service
from app.config import settings

# cryptography for RSA verify & AES-GCM decrypt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding as asy_padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# 运行模式：prod 严格校验；dev 跳过校验便于联调
PAY_MODE: str = getattr(settings, "wechat_pay_mode", "dev")  # 'prod' or 'dev'

# v3 key（32字节）与平台公钥（PEM 文本或路径）
API_V3_KEY: Optional[str] = getattr(settings, "wechat_api_v3_key", None)
PLATFORM_PUBKEY_PEM: Optional[str] = getattr(settings, "wechat_platform_public_key_pem", None)
PLATFORM_PUBKEY_PATH: Optional[str] = getattr(settings, "wechat_platform_public_key_path", None)


@dataclass
class WxHeaders:
    timestamp: str
    nonce: str
    signature: str
    serial: str


def _load_platform_pubkey() -> Optional[bytes]:
    if PLATFORM_PUBKEY_PEM:
        return PLATFORM_PUBKEY_PEM.encode("utf-8")
    if PLATFORM_PUBKEY_PATH:
        with open(PLATFORM_PUBKEY_PATH, "rb") as f:
            return f.read()
    return None


def _verify_signature(headers: WxHeaders, body: bytes) -> None:
    pem = _load_platform_pubkey()
    if not pem:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WeChat platform public key not configured",
        )

    message = f"{headers.timestamp}\n{headers.nonce}\n{body.decode('utf-8')}\n".encode("utf-8")
    public_key = load_pem_public_key(pem)  # type: ignore[arg-type]
    try:
        public_key.verify(
            base64.b64decode(headers.signature),
            message,
            asy_padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WeChat Pay signature")


def _decrypt_resource(resource: dict) -> dict:
    if not API_V3_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WeChat APIv3 key not configured",
        )

    try:
        key = API_V3_KEY.encode("utf-8")
        ciphertext = base64.b64decode(resource["ciphertext"])
        aad = resource.get("associated_data", "")
        nonce = resource["nonce"].encode("utf-8")
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, aad.encode("utf-8") if aad else None)
        return json.loads(plaintext.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to decrypt WeChat resource")


def _log_webhook(db: Session, *, source: str, event_type: Optional[str], payload_text: str, processed: bool) -> None:
    log = WebhookLog(source=source, event_type=event_type, payload=payload_text, processed=processed)
    db.add(log)
    db.flush()


@router.post("/wechatpay")
async def wechatpay_callback(request: Request, db: Session = Depends(get_db_tx)):
    """
    微信支付 v3 回调：
    - prod：验签 + 解密；仅处理 TRANSACTION.SUCCESS
    - dev ：跳过验签解密，直接按 body 处理（便于联调）
    成功时：标记支付成功 + 授予权益
    """
    body_bytes = await request.body()
    payload_text = body_bytes.decode("utf-8") or "{}"

    headers = WxHeaders(
        timestamp=request.headers.get("Wechatpay-Timestamp", ""),
        nonce=request.headers.get("Wechatpay-Nonce", ""),
        signature=request.headers.get("Wechatpay-Signature", ""),
        serial=request.headers.get("Wechatpay-Serial", ""),
    )

    try:
        if PAY_MODE == "prod":
            # 1) 验签
            _verify_signature(headers, body_bytes)
            # 2) 解密
            outer = json.loads(payload_text)
            event_type = outer.get("event_type")
            resource = outer.get("resource") or {}
            resource_plain = _decrypt_resource(resource)

            processed = False
            if event_type == "TRANSACTION.SUCCESS":
                out_trade_no = resource_plain.get("out_trade_no")
                transaction_id = resource_plain.get("transaction_id")
                if not out_trade_no or not transaction_id:
                    raise HTTPException(status_code=400, detail="Invalid transaction payload")

                # 找订单
                order = db.query(Order).filter(Order.out_trade_no == str(out_trade_no)).first()  # type: ignore
                if not order:
                    raise HTTPException(status_code=404, detail="Order not found")

                # 支付成功
                pay_service.mark_success(db, order=order, transaction_id=str(transaction_id), raw=payload_text)

                # ✅ 发放权益：基于订单的用户与商品编码（lazy-load OK）
                ent_service.grant(db, user=order.user, product_code=order.product.code)  # type: ignore[attr-defined]

                processed = True

            _log_webhook(db, source="WECHAT", event_type=outer.get("event_type"), payload_text=payload_text, processed=processed)
            return {"code": "SUCCESS", "message": "成功" if processed else "ignored"}

        else:
            # 开发模式：允许直接传 {"out_trade_no":"...", "transaction_id":"..."}
            data = json.loads(payload_text)
            out_trade_no = data.get("out_trade_no")
            transaction_id = data.get("transaction_id", "dev_txn")
            event_type = data.get("event_type", "TRANSACTION.SUCCESS")

            processed = False
            if event_type == "TRANSACTION.SUCCESS" and out_trade_no:
                order = db.query(Order).filter(Order.out_trade_no == str(out_trade_no)).first()  # type: ignore
                if not order:
                    raise HTTPException(status_code=404, detail="Order not found")

                pay_service.mark_success(db, order=order, transaction_id=str(transaction_id), raw=payload_text)

                # ✅ 发放权益（开发模式同样执行）
                ent_service.grant(db, user=order.user, product_code=order.product.code)  # type: ignore[attr-defined]

                processed = True

            _log_webhook(db, source="WECHAT", event_type=event_type, payload_text=payload_text, processed=processed)
            return {"code": "SUCCESS", "message": "dev processed" if processed else "dev ignored"}

    except HTTPException as e:
        try:
            _log_webhook(db, source="WECHAT", event_type=None, payload_text=payload_text, processed=False)
        finally:
            return ({"code": "FAIL", "message": e.detail if isinstance(e.detail, str) else "error"}, e.status_code)
    except Exception:
        try:
            _log_webhook(db, source="WECHAT", event_type=None, payload_text=payload_text, processed=False)
        finally:
            return {"code": "FAIL", "message": "internal error"}, 500
