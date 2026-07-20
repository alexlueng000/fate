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


class QuotaLedger(Base):
    """Immutable audit entry for every quota grant, use, or reversal."""

    __tablename__ = "quota_ledger"

    id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quota_type: Mapped[str] = mapped_column(String(50), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(
        UBIGINT(unsigned=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=True,
    )
    refund_id: Mapped[Optional[int]] = mapped_column(
        UBIGINT(unsigned=True),
        ForeignKey("refunds.id", ondelete="RESTRICT"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[user_id]
    )
    order: Mapped[Optional["Order"]] = relationship(  # type: ignore[name-defined]
        "Order", foreign_keys=[order_id]
    )
    refund: Mapped[Optional["Refund"]] = relationship(  # type: ignore[name-defined]
        "Refund", foreign_keys=[refund_id]
    )

    __table_args__ = (
        CheckConstraint("delta <> 0", name="ck_quota_ledger_delta_nonzero"),
        UniqueConstraint("idempotency_key", name="uk_quota_ledger_idempotency_key"),
        Index("ix_quota_ledger_user_type_created", "user_id", "quota_type", "created_at"),
        Index("ix_quota_ledger_order_id", "order_id"),
        Index("ix_quota_ledger_refund_id", "refund_id"),
    )
