"""Order-scoped reading passes; legacy quota tables remain unchanged."""
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class ConsultationPass(Base):
    __tablename__ = "consultation_passes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    duration_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    reply_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    replies_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class ConsultationRequest(Base):
    __tablename__ = "consultation_requests"
    __table_args__ = (UniqueConstraint("user_id", "request_key", name="uq_consult_request"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pass_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    reply: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
