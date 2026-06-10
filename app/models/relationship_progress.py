# app/models/relationship_progress.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class RelationshipProgress(Base):
    """Relationship task progress and review reminder snapshots."""

    __tablename__ = "relationship_progress"

    __table_args__ = (
        Index("idx_relationship_progress_user_updated", "user_id", "updated_at"),
        Index("idx_relationship_progress_user_task", "user_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="Primary key",
    )

    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owner user id",
    )

    task_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        comment="Stable relationship task identifier from frontend task context",
    )

    task_context: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="Relationship task snapshot",
    )

    content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Progress note content",
    )

    review_due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
        comment="Optional review reminder time",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
        comment="Created time",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
        comment="Updated time",
    )

    user = relationship("User", passive_deletes=True)
