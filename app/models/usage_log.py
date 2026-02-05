# app/models/usage_log.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    DateTime,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UsageLog(Base):
    """
    使用日志表
    - 记录用户的每次使用行为，用于详细审计和统计
    """
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # 使用类型: chat_start, chat_send, report_generate 等
    usage_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="使用类型: chat_start, chat_send 等",
    )

    # 关联的对话ID（可选）
    conversation_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联的对话ID",
    )

    # Token 统计
    prompt_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="输入 token 数",
    )

    completion_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="输出 token 数",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_usage_logs_user_time", "user_id", "created_at"),
        Index("ix_usage_logs_type", "usage_type"),
    )

    @property
    def total_tokens(self) -> int:
        """总 token 数"""
        return self.prompt_tokens + self.completion_tokens

    def __repr__(self) -> str:
        return f"<UsageLog id={self.id} user_id={self.user_id} type={self.usage_type}>"
