from pydantic import BaseModel, Field
from typing import Literal, List, Optional, Any

# Auth
class LoginRequest(BaseModel):
    js_code: str
    nickname: Optional[str] = None
    avatar: Optional[str] = None

class TokenResponse(BaseModel):
    token: str

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
