from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal, Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, String, Text, Time, func
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, JSON, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


GuestAnalysisStatus = Literal["pending", "running", "succeeded", "failed", "expired"]
GenderType = Literal["male", "female"]
CalendarType = Literal["solar", "lunar"]


class GuestAnalysis(Base):
    __tablename__ = "guest_analysis"

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    guest_session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[GuestAnalysisStatus] = mapped_column(
        Enum("pending", "running", "succeeded", "failed", "expired", name="guest_analysis_status"),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    display_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    gender: Mapped[GenderType] = mapped_column(Enum("male", "female", name="guest_analysis_gender"), nullable=False)
    calendar_type: Mapped[CalendarType] = mapped_column(
        Enum("solar", "lunar", name="guest_analysis_calendar_type"),
        nullable=False,
        default="solar",
        server_default="solar",
    )
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    birth_time: Mapped[time] = mapped_column(Time, nullable=False)
    birth_location: Mapped[str] = mapped_column(String(100), nullable=False)
    birth_longitude: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6), nullable=True)
    birth_latitude: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai")

    bazi_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    analysis_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
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
        Index("idx_guest_analysis_session_created", "guest_session_id", "created_at"),
        Index("idx_guest_analysis_user_created", "user_id", "created_at"),
        Index("idx_guest_analysis_status_created", "status", "created_at"),
        Index("idx_guest_analysis_expires_at", "expires_at"),
        Index("idx_guest_analysis_request_ip_created", "request_ip", "created_at"),
    )
