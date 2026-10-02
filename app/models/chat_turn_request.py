"""Durable attempts and a unique active slot for ordinary saved conversations."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, JSON
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class ChatTurnRequest(Base):
    __tablename__ = 'chat_turn_requests'
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey('conversations.id', ondelete='CASCADE'), index=True)
    # NULL for terminal attempts; a database constraint also protects engines
    # without effective SELECT FOR UPDATE from two live conversation slots.
    active_conversation_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    payload_hash: Mapped[str] = mapped_column(String(64))
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(16))
    token: Mapped[str] = mapped_column(String(32))
    baseline_message_id: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lease_until: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime().with_variant(DATETIME(fsp=6), 'mysql'), default=datetime.utcnow)
