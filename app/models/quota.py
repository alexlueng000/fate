# app/models/quota.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    DateTime,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UserQuota(Base):
    """
    用户配额表
    - 记录用户的各类配额（如聊天次数、报告次数等）
    - total_quota = -1 表示无限制
    """
    __tablename__ = "user_quotas"

    id: Mapped[int] = mapped_column(
        Integer,
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

    # 配额类型: chat, report 等
    quota_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="chat",
        comment="配额类型: chat, report 等",
    )

    # 总配额, -1 表示无限制
    total_quota: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=-1,
        comment="总配额, -1 表示无限制",
    )

    # 已使用次数
    used_quota: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="已使用次数",
    )

    # 重置周期: daily, monthly, never
    period: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="never",
        comment="重置周期: daily, monthly, never",
    )

    # 上次重置时间
    last_reset_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
        comment="上次重置时间",
    )

    # 来源: free, paid, admin_grant
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="free",
        comment="来源: free, paid, admin_grant",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "quota_type", name="uk_user_quota_type"),
        Index("ix_user_quotas_user_type", "user_id", "quota_type"),
    )

    @property
    def remaining(self) -> int:
        """剩余配额，-1 表示无限制"""
        if self.total_quota == -1:
            return -1
        return max(0, self.total_quota - self.used_quota)

    @property
    def is_unlimited(self) -> bool:
        """是否无限制"""
        return self.total_quota == -1

    def __repr__(self) -> str:
        return f"<UserQuota id={self.id} user_id={self.user_id} type={self.quota_type} used={self.used_quota}/{self.total_quota}>"
