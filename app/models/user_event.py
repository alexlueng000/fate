# app/models/user_event.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UserEvent(Base):
    """Small behavioral event record for product retention analysis."""

    __tablename__ = "user_events"

    __table_args__ = (
        Index("idx_user_events_user_created", "user_id", "created_at"),
        Index("idx_user_events_name_created", "event_name", "created_at"),
        Index("idx_user_events_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="Primary key",
    )

    user_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Logged-in user id; null for anonymous events",
    )

    event_name: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment="Event name",
    )

    event_source: Mapped[Optional[str]] = mapped_column(
        String(40),
        nullable=True,
        comment="Client source",
    )

    page_path: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Current page path",
    )

    payload: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="Small structured event payload",
    )

    session_id: Mapped[Optional[str]] = mapped_column(
        String(80),
        nullable=True,
        comment="Client session id",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
        comment="Created time",
    )

    user = relationship("User", passive_deletes=True)

