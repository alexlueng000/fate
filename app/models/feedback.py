# app/models/feedback.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Feedback(Base):
    """用户反馈表"""
    __tablename__ = "feedbacks"

    __table_args__ = (
        Index("idx_feedbacks_user_id", "user_id"),
        Index("idx_feedbacks_status", "status"),
        Index("idx_feedbacks_type", "type"),
        Index("idx_feedbacks_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键ID")
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="用户ID"
    )
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="other", comment="反馈类型: bug/feature/question/other"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="反馈内容")
    contact: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="联系方式"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", comment="状态: pending/processing/resolved/closed"
    )
    admin_reply: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="管理员回复"
    )
    replied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="回复时间"
    )
    replied_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="回复管理员ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关联关系
    user = relationship("User", foreign_keys=[user_id], backref="feedbacks")
    admin = relationship("User", foreign_keys=[replied_by])
