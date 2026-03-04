# app/models/message_rating.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    DateTime,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.mysql import JSON

from app.db import Base


class MessageRating(Base):
    """消息评价模型 - 记录用户对AI回复的点赞/点踩评价"""
    __tablename__ = "message_ratings"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        nullable=False,
    )

    message_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    rating_type: Mapped[str] = mapped_column(
        Enum("up", "down", name="rating_type"),
        nullable=False,
    )

    reason: Mapped[Optional[str]] = mapped_column(
        String(500),  # 扩展到 500 字符以支持自定义理由
        nullable=True,
    )

    # 命盘数据（点踩时保存，用于后续分析）
    paipan_data: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
    )

    # 关系
    message = relationship("Message", backref="ratings")
    user = relationship("User", backref="message_ratings")

    __table_args__ = (
        Index("idx_message_ratings_message_user", "message_id", "user_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<MessageRating id={self.id} message_id={self.message_id} type={self.rating_type}>"
