from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT as UBIGINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Refund(Base):
    """A merchant refund request and its latest WeChat Pay state."""

    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    order_id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    out_refund_no: Mapped[str] = mapped_column(String(64), nullable=False)
    wechat_refund_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    refund_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    requested_by: Mapped[Optional[int]] = mapped_column(
        UBIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    success_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_request: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    order: Mapped["Order"] = relationship(  # type: ignore[name-defined]
        "Order", foreign_keys=[order_id]
    )
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[user_id]
    )
    requester: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[requested_by]
    )

    __table_args__ = (
        CheckConstraint("refund_cents > 0", name="ck_refunds_refund_cents_positive"),
        CheckConstraint(
            "total_cents >= refund_cents", name="ck_refunds_total_covers_refund"
        ),
        UniqueConstraint("out_refund_no", name="uk_refunds_out_refund_no"),
        UniqueConstraint("wechat_refund_id", name="uk_refunds_wechat_refund_id"),
        Index("ix_refunds_order_status", "order_id", "status"),
        Index("ix_refunds_user_id", "user_id"),
    )
