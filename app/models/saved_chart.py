# app/models/saved_chart.py
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from .user import User


class SavedChart(Base):
    """用户保存的命盘"""
    __tablename__ = "saved_charts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="命盘名称")
    encrypted_birth_info: Mapped[str] = mapped_column(Text, nullable=False, comment="加密的出生信息(JSON)")
    encrypted_chart_data: Mapped[str] = mapped_column(Text, nullable=False, comment="加密的命盘数据(JSON)")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否默认命盘")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="saved_charts")
