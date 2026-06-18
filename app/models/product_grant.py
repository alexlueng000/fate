from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.mysql import BIGINT as UBIGINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ProductGrant(Base):
    __tablename__ = "product_grants"

    id: Mapped[int] = mapped_column(UBIGINT(unsigned=True), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    quota_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    product: Mapped["Product"] = relationship("Product", back_populates="grants")  # type: ignore[name-defined]
