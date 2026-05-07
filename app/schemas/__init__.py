from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


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
    ALIPAY_PC = "ALIPAY_PC"
    ALIPAY_H5 = "ALIPAY_H5"


# =========================
# Product
# =========================
class ProductOut(BaseModel):
    id: int
    code: str
    name: str
    price_cents: int
    currency: str = "CNY"
    quota_amount: int
    description: Optional[str] = None
    active: bool

    model_config = dict(from_attributes=True)


# =========================
# Order
# =========================
class OrderCreate(BaseModel):
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
    pay_url: Optional[str] = None   # 支付宝PC/H5支付跳转URL
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
# Simulate Payment (开发/演示用)
# =========================
class SimulatePaymentIn(BaseModel):
    product_code: str = Field(..., description="商品编码，例如 basic_combo / premium_combo")


class QuotaSnapshot(BaseModel):
    """单条 quota 快照，用于购买后同步前端显示。"""
    type: str
    total: int
    used: int
    remaining: int
    is_unlimited: bool


class SimulatePaymentOut(BaseModel):
    order_id: int
    product_code: str
    granted: Dict[str, int] = Field(
        default_factory=dict,
        description="本次发放明细，例如 {\"bazi\": 10, \"liuyao\": 3}",
    )
    quotas: List[QuotaSnapshot] = Field(
        default_factory=list,
        description="发放后用户全部配额快照",
    )
