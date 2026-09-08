"""Derived history metadata; conversations remain the source of truth."""
from datetime import datetime
from typing import Optional
from sqlalchemy import ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class ConversationDigest(Base):
    __tablename__ = "conversation_digests"
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    custom_title: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    topic: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="empty", nullable=False)
    source_message_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_token: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
