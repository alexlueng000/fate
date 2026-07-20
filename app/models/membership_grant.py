from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT as UBIGINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class MembershipGrant(Base):
    """Membership period contributed by one paid order."""

    __tablename__ = "membership_grants"

    id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    refund_id: Mapped[Optional[int]] = mapped_column(
        UBIGINT(unsigned=True),
        ForeignKey("refunds.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[user_id]
    )
    order: Mapped["Order"] = relationship(  # type: ignore[name-defined]
        "Order", foreign_keys=[order_id]
    )
    product: Mapped["Product"] = relationship(  # type: ignore[name-defined]
        "Product", foreign_keys=[product_id]
    )
    refund: Mapped[Optional["Refund"]] = relationship(  # type: ignore[name-defined]
        "Refund", foreign_keys=[refund_id]
    )

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_membership_grants_valid_period"),
        UniqueConstraint("order_id", name="uk_membership_grants_order_id"),
        Index("ix_membership_grants_user_status_end", "user_id", "status", "ends_at"),
        Index("ix_membership_grants_refund_id", "refund_id"),
    )
