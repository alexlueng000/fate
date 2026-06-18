from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.mysql import BIGINT as UBIGINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UserMembership(Base):
    __tablename__ = "user_memberships"

    id: Mapped[int] = mapped_column(UBIGINT(unsigned=True), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        UBIGINT(unsigned=True), ForeignKey("orders.id", ondelete="SET NULL"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # type: ignore[name-defined]
    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id])  # type: ignore[name-defined]
    order: Mapped[Optional["Order"]] = relationship("Order", foreign_keys=[order_id])  # type: ignore[name-defined]
