from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.mysql import BIGINT, JSON, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


GuestLiuyaoStatus = Literal["running", "succeeded", "failed", "expired"]


class GuestLiuyao(Base):
    __tablename__ = "guest_liuyao"

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    guest_session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[GuestLiuyaoStatus] = mapped_column(
        Enum("running", "succeeded", "failed", "expired", name="guest_liuyao_status"),
        nullable=False,
        default="running",
        server_default="running",
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    gender: Mapped[str] = mapped_column(
        Enum("male", "female", "unknown", name="guest_liuyao_gender"),
        default="unknown",
        server_default="unknown",
        nullable=False,
    )
    method: Mapped[str] = mapped_column(
        Enum("number", "coin", "time", name="guest_liuyao_method"),
        nullable=False,
    )
    numbers: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    location: Mapped[str] = mapped_column(String(50), default="beijing", server_default="beijing", nullable=False)
    solar_time: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    hexagram_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    analysis_markdown: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT, nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    request_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    bound_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_guest_liuyao_session_created", "guest_session_id", "created_at"),
        Index("idx_guest_liuyao_user_created", "user_id", "created_at"),
        Index("idx_guest_liuyao_status_created", "status", "created_at"),
        Index("idx_guest_liuyao_expires_at", "expires_at"),
        Index("idx_guest_liuyao_request_ip_created", "request_ip", "created_at"),
    )
