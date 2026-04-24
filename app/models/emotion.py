# app/models/emotion.py
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    DateTime,
    SmallInteger,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from .user import User


class EmotionRecord(Base):
    """
    情绪记录表 - 心镜灯核心数据
    记录用户每日的情绪状态、节气、五行等信息
    """
    __tablename__ = "emotion_records"

    __table_args__ = (
        Index("ix_emotion_user_date", "user_id", "record_date"),
        Index("ix_emotion_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="主键ID"
    )

    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID"
    )

    record_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        comment="记录日期（用户本地日期）"
    )

    solar_term: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        comment="当前节气（如：立春、雨水）"
    )

    wuxing_element: Mapped[Optional[str]] = mapped_column(
        String(16),
        nullable=True,
        comment="五行属性（金/木/水/火/土）"
    )

    emotion_score: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        comment="情绪评分 1-10"
    )

    emotion_tags: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="情绪标签（JSON数组字符串）"
    )

    content: Mapped[str] = mapped_column(
        mysql.TEXT().with_variant(Text, "sqlite"),
        nullable=False,
        comment="情绪记录内容"
    )

    ai_response: Mapped[Optional[str]] = mapped_column(
        mysql.MEDIUMTEXT().with_variant(Text, "sqlite"),
        nullable=True,
        comment="AI回应内容"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
        comment="创建时间"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
        comment="更新时间"
    )

    # 关系
    user: Mapped["User"] = relationship(passive_deletes=True)

    def __repr__(self) -> str:
        return f"<EmotionRecord id={self.id} user_id={self.user_id} date={self.record_date}>"


class ExceptionMoment(Base):
    """
    例外时刻表 - 记录用户的积极例外事件
    """
    __tablename__ = "exception_moments"

    __table_args__ = (
        Index("ix_exception_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="主键ID"
    )

    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID"
    )

    emotion_record_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("emotion_records.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联的情绪记录ID"
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="例外时刻标题"
    )

    content: Mapped[str] = mapped_column(
        mysql.TEXT().with_variant(Text, "sqlite"),
        nullable=False,
        comment="例外时刻详细描述"
    )

    moment_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        comment="例外时刻发生日期"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
        comment="创建时间"
    )

    # 关系
    user: Mapped["User"] = relationship(passive_deletes=True)

    def __repr__(self) -> str:
        return f"<ExceptionMoment id={self.id} user_id={self.user_id} title={self.title!r}>"


class ValueAction(Base):
    """
    价值行动表 - 记录用户的价值观和行动计划
    """
    __tablename__ = "value_actions"

    __table_args__ = (
        Index("ix_value_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="主键ID"
    )

    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID"
    )

    emotion_record_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("emotion_records.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联的情绪记录ID"
    )

    value_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="价值观名称"
    )

    action_plan: Mapped[str] = mapped_column(
        mysql.TEXT().with_variant(Text, "sqlite"),
        nullable=False,
        comment="行动计划"
    )

    status: Mapped[int] = mapped_column(
        SmallInteger,
        default=0,
        server_default="0",
        nullable=False,
        comment="状态：0=计划中, 1=进行中, 2=已完成"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
        comment="创建时间"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
        comment="更新时间"
    )

    # 关系
    user: Mapped["User"] = relationship(passive_deletes=True)

    def __repr__(self) -> str:
        return f"<ValueAction id={self.id} user_id={self.user_id} value={self.value_name!r}>"
