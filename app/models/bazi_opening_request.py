"""A durable first report for an owned chart and explicit task background."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class BaziOpeningRequest(Base):
    __tablename__ = 'bazi_opening_requests'
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(32), unique=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey('conversations.id', ondelete='CASCADE'), unique=True)
    # Keep the first accepted model settings and source identity for retries.
    request_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
