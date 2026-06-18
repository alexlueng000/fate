from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="one_time",
        server_default="one_time",
        comment="Product kind: one_time, subscription, topup",
    )
    period: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Billing period for subscription products",
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)

    # Legacy compatibility fields. New products should use product_grants.
    quota_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bazi_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    liuyao_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    features: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    grants: Mapped[list["ProductGrant"]] = relationship(  # type: ignore[name-defined]
        "ProductGrant",
        back_populates="product",
        cascade="all,delete-orphan",
        lazy="selectin",
    )
