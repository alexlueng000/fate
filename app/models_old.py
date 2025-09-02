from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    String, Integer, DateTime, ForeignKey, Text, Boolean, UniqueConstraint, func
)
from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    # 方便反查
    orders: Mapped[list["Order"]] = relationship(
        back_populates="user", cascade="all,delete-orphan", passive_deletes=True
    )
    entitlements: Mapped[list["Entitlement"]] = relationship(
        back_populates="user", cascade="all,delete-orphan", passive_deletes=True
    )

class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)  # e.g. REPORT_UNLOCK
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)  # 990 = 9.90
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    orders: Mapped[list["Order"]] = relationship(
        back_populates="product", cascade="all,delete-orphan", passive_deletes=True
    )

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="CREATED", nullable=False
    )  # CREATED, PAID, CANCELED, REFUNDED
    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)  # 商户单号
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="orders")
    product: Mapped["Product"] = relationship(back_populates="orders")
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="order", cascade="all,delete-orphan", passive_deletes=True
    )



class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # WECHAT_JSAPI / WECHAT_NATIVE
    prepay_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 微信支付单号
    status: Mapped[str] = mapped_column(
        String(20), default="PENDING", nullable=False
    )  # PENDING, SUCCESS, FAIL
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    order: Mapped["Order"] = relationship(back_populates="payments")


class Entitlement(Base):
    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("user_id", "product_code", name="uq_user_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_code: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="entitlements")


class WebhookLog(Base):
    __tablename__ = "webhooks_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # WECHAT
    event_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)