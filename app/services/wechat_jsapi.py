"""Public-account OAuth and WeChat Pay v3 JSAPI checkout for the website."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx
from jose import JWTError, jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from app.config import settings
from app.models import Payment
from app.services import payments


def require_config() -> str:
    if not settings.wechat_jsapi_enabled or settings.wechat_pay_mode != "prod":
        raise ValueError("微信内支付暂未开通，请在电脑上打开网站后使用微信扫码支付。")
    if not settings.wechat_jsapi_appid or not settings.wechat_jsapi_secret:
        raise ValueError("微信公众号支付配置不完整，请联系管理员。")
    if not (settings.wechat_pay_mchid and settings.wechat_pay_merchant_serial_no
            and settings.wechat_pay_notify_url
            and (settings.wechat_pay_private_key_path or settings.wechat_pay_private_key_pem)
            and (settings.wechat_platform_public_key_path or settings.wechat_platform_public_key_pem)):
        raise ValueError("微信支付商户配置不完整，请联系管理员。")
    if not settings.wechat_api_v3_key or len(settings.wechat_api_v3_key.encode()) != 32:
        raise ValueError("微信支付通知解密密钥配置不完整，请联系管理员。")
    if settings.jwt_secret == "change-me" or len(settings.jwt_secret) < 32:
        raise ValueError("支付授权签名密钥配置不完整，请联系管理员。")
    return settings.wechat_jsapi_appid


def _ticket_key() -> bytes:
    # Purpose-separated key: an OAuth ticket must never work as a login token.
    return hmac.new(settings.jwt_secret.encode(), b"website-wechat-pay-oauth", hashlib.sha256).digest()


def authorize(*, user_id: int, product_code: str, redirect_uri: str) -> dict:
    appid = require_config()
    parsed = urlsplit(redirect_uri)
    allowed = {origin.strip().rstrip("/") for origin in settings.wechat_jsapi_origins.split(",")}
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or f"{parsed.scheme}://{parsed.netloc}" not in allowed
            or parsed.path not in ("/pricing", "/membership") or parsed.query or parsed.fragment):
        raise ValueError("支付授权回跳地址不合法。")
    nonce = secrets.token_hex(16)
    ticket = jwt.encode({
        "sub": str(user_id), "product_code": product_code, "nonce": nonce,
        "exp": int(time.time()) + 600, "aud": "wechat-jsapi",
    }, _ticket_key(), algorithm="HS256")
    query = urlencode({"appid": appid, "redirect_uri": redirect_uri,
                       "response_type": "code", "scope": "snsapi_base", "state": nonce})
    return {"url": f"https://open.weixin.qq.com/connect/oauth2/authorize?{query}#wechat_redirect",
            "state": nonce, "ticket": ticket}


def validate_ticket(*, user_id: int, ticket: str, state: str) -> str:
    try:
        payload = jwt.decode(ticket, _ticket_key(), algorithms=["HS256"], audience="wechat-jsapi")
        if (payload.get("sub") != str(user_id) or not state
                or not secrets.compare_digest(payload.get("nonce", ""), state)
                or not payload.get("product_code")):
            raise ValueError("invalid binding")
        return payload["product_code"]
    except (JWTError, ValueError, TypeError) as exc:
        raise ValueError("支付授权已失效，请重新选择套餐。") from exc


def exchange_openid(code: str) -> str:
    appid = require_config()
    with httpx.Client(timeout=15) as client:
        response = client.get("https://api.weixin.qq.com/sns/oauth2/access_token", params={
            "appid": appid, "secret": settings.wechat_jsapi_secret,
            "code": code, "grant_type": "authorization_code",
        })
    # Do not expose upstream text, request URLs, access tokens or AppSecret.
    if response.status_code != 200:
        raise ValueError("微信授权服务暂不可用，请重新选择套餐。")
    data = response.json()
    if data.get("errcode") or not data.get("openid"):
        raise ValueError("微信授权失败或已过期，请重新选择套餐。")
    return data["openid"]


def payment_params(prepay_id: str) -> dict:
    appid = require_config()
    timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
    package = f"prepay_id={prepay_id}"
    message = f"{appid}\n{timestamp}\n{nonce}\n{package}\n".encode()
    key = load_pem_private_key(payments._load_merchant_private_key(), password=None)
    signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return {"appId": appid, "timeStamp": timestamp, "nonceStr": nonce,
            "package": package, "signType": "RSA",
            "paySign": base64.b64encode(signature).decode()}


def create_prepay(db, *, order, openid: str):
    appid = require_config()
    if order.status != "CREATED" or not openid:
        raise ValueError("订单状态或微信授权无效。")
    path = "/v3/pay/transactions/jsapi"
    body = json.dumps({
        "appid": appid, "mchid": settings.wechat_pay_mchid,
        "description": order.product.name[:127], "out_trade_no": order.out_trade_no,
        "notify_url": payments._wechat_notify_url(),
        "amount": {"total": order.amount_cents, "currency": order.currency},
        "payer": {"openid": openid},
    }, ensure_ascii=False, separators=(",", ":"))
    with httpx.Client(timeout=15) as client:
        response = client.post(f"https://api.mch.weixin.qq.com{path}", content=body.encode(), headers={
            "Authorization": payments._wechat_auth_header("POST", path, body),
            "Accept": "application/json", "Content-Type": "application/json",
        })
    if response.status_code >= 400:
        raise ValueError("微信支付下单失败，请稍后重试或联系管理员检查商户权限。")
    payments.verify_wechat_response(response)
    prepay_id = response.json().get("prepay_id")
    if not prepay_id:
        raise ValueError("微信支付未返回预支付凭据。")
    params = payment_params(prepay_id)
    payment = Payment(order_id=order.id, channel="WECHAT_JSAPI", prepay_id=prepay_id,
                      status="PENDING", raw=response.text)
    db.add(payment)
    db.flush()
    return payment, params
