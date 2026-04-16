# app/models/profile.py
from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Literal, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    func,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from .user import User

GenderType = Literal["male", "female"]
CalendarType = Literal["solar", "lunar"]


class UserProfile(Base):
    """
    用户命盘档案表
    - 方案一：一个用户只有一个默认档案（通过 UNIQUE 约束保证）
    - 存储出生信息和计算好的命盘数据
    - 所有聊天会话绑定到此档案
    """
    __tablename__ = "user_profiles"

    __table_args__ = (
        Index("ix_user_profiles_created_at", "created_at"),
    )

    # === 主键 ===
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="主键ID"
    )

    # === 关联用户（唯一约束：一个用户一个档案） ===
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,  # 保证一个用户只有一个档案
        nullable=False,
        comment="关联用户ID（外键 users.id）"
    )

    # === 出生信息 ===
    gender: Mapped[GenderType] = mapped_column(
        Enum("male", "female", name="gender_type"),
        nullable=False,
        comment="性别：male=男, female=女"
    )

    calendar_type: Mapped[CalendarType] = mapped_column(
        Enum("solar", "lunar", name="calendar_type"),
        nullable=False,
        default="solar",
        server_default="solar",
        comment="历法类型：solar=阳历, lunar=农历"
    )

    birth_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="出生日期（YYYY-MM-DD）"
    )

    birth_time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        comment="出生时间（HH:MM:SS）"
    )

    birth_location: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="出生地点（城市名称，如'深圳'）"
    )

    birth_longitude: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 6),
        nullable=True,
        comment="出生地经度（用于真太阳时计算）"
    )

    birth_latitude: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 6),
        nullable=True,
        comment="出生地纬度（备用）"
    )

    # === 命盘数据（JSON 格式） ===
    bazi_chart: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="八字命盘数据（包含四柱、大运等完整信息）"
    )

    # === 时间戳 ===
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        comment="创建时间"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
        comment="更新时间"
    )

    # === 关联关系 ===
    user: Mapped["User"] = relationship(
        back_populates="profile",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<UserProfile id={self.id} user_id={self.user_id} "
            f"gender={self.gender} birth_date={self.birth_date}>"
        )

    @property
    def birth_datetime_str(self) -> str:
        """返回格式化的出生日期时间字符串，用于前端显示"""
        return f"{self.birth_date.strftime('%Y-%m-%d')} {self.birth_time.strftime('%H:%M')}"

    @property
    def display_info(self) -> str:
        """返回简短的档案信息，用于聊天页顶部显示"""
        gender_cn = "男" if self.gender == "male" else "女"
        return f"{gender_cn}｜{self.birth_date.strftime('%Y-%m-%d')} {self.birth_time.strftime('%H:%M')}｜{self.birth_location}"
