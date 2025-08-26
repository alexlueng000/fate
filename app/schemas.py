from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Literal, List, Optional

# Auth
class LoginIn(BaseModel):
    js_code: str
    nickname: str | None = None

class LoginOut(BaseModel):
    openid: str
    unionid: str | None = None
    session_key: str | None = None
    access_token: str



# Chat
class Msg(BaseModel):
    role: Literal["user","assistant","system"]
    content: str

class ChatRequest(BaseModel):
    messages: List[Msg]

class ChatResponse(BaseModel):
    reply: str

# Bazi
class BaziComputeRequest(BaseModel):
    birth_ts: int           # 秒级时间戳
    calendar: Literal["solar","lunar"]
    city: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

class BaziComputeResponse(BaseModel):
    profile_id: int
    table: dict
    dayun: list
    wuxing: list

# Product
class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    type: str
    price: int
    currency: str

# Order & Pay
class CreateOrderRequest(BaseModel):
    sku: str

class OrderOut(BaseModel):
    order_id: int
    amount: int
    status: str

class PrepayRequest(BaseModel):
    order_id: int
    openid: str

class PrepayResponse(BaseModel):
    prepay_id: str
    pay_params: dict

# WeChat notify
class NotifyResult(BaseModel):
    ok: bool



# =========================
# 公用枚举
# =========================
class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PAID = "PAID"
    CANCELED = "CANCELED"
    REFUNDED = "REFUNDED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"


class PayChannel(str, Enum):
    WECHAT_JSAPI = "WECHAT_JSAPI"
    WECHAT_NATIVE = "WECHAT_NATIVE"


# =========================
# User
# =========================
class UserBase(BaseModel):
    nickname: Optional[str] = None


class UserCreate(UserBase):
    openid: str = Field(..., min_length=1)
    is_admin: Optional[bool] = False


class UserUpdate(UserBase):
    is_admin: Optional[bool] = None


class UserOut(UserBase):
    id: int
    openid: str
    is_admin: bool
    created_at: datetime

    model_config = dict(from_attributes=True)


# =========================
# Product
# =========================
class ProductBase(BaseModel):
    code: str
    name: str
    price_cents: int = Field(..., ge=0)
    currency: str = "CNY"
    active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductOut(ProductBase):
    id: int

    model_config = dict(from_attributes=True)


# =========================
# Order
# =========================
class OrderCreate(BaseModel):
    # 业务侧下单通常用 product_code，更稳；也可另做 OrderCreateById
    product_code: Optional[str] = None


class OrderOut(BaseModel):
    id: int
    user_id: int
    product_id: int
    amount_cents: int
    currency: str
    status: OrderStatus
    out_trade_no: str
    created_at: datetime

    model_config = dict(from_attributes=True)


# =========================
# Payment
# =========================
class PaymentPrepayCreate(BaseModel):
    order_id: int
    channel: PayChannel


class PaymentOut(BaseModel):
    id: int
    order_id: int
    channel: PayChannel
    prepay_id: Optional[str] = None
    transaction_id: Optional[str] = None
    status: PaymentStatus
    raw: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = dict(from_attributes=True)


# =========================
# Entitlement
# =========================
class EntitlementOut(BaseModel):
    id: int
    user_id: int
    product_code: str
    granted_at: datetime

    model_config = dict(from_attributes=True)


# =========================
# Webhook Log
# =========================
class WebhookLogOut(BaseModel):
    id: int
    source: str
    event_type: Optional[str] = None
    payload: str
    processed: bool
    created_at: datetime

    model_config = dict(from_attributes=True)


# =========================
# Auth / Token
# =========================
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    # 开发态可直接传 openid；如果你做微信 js_code 交换，也可定义 js_code: str
    openid: Optional[str] = None
    js_code: Optional[str] = None
    nickname: Optional[str] = None