# app/models/liuyao.py
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    Text,
    DateTime,
    Boolean,
    Enum,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from .user import User


class LiuyaoHexagram(Base):
    """
    六爻卦象记录表
    存储用户的六爻起卦和解卦记录
    """
    __tablename__ = "liuyao_hexagrams"

    __table_args__ = (
        Index("ix_liuyao_user_created", "user_id", "created_at"),
        Index("ix_liuyao_hexagram_id", "hexagram_id"),
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

    hexagram_id: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        comment="卦象唯一ID（用于URL访问）"
    )

    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="问事内容"
    )

    gender: Mapped[str] = mapped_column(
        Enum("male", "female", "unknown", name="gender_enum"),
        default="unknown",
        nullable=False,
        comment="性别：male=男, female=女, unknown=未知"
    )

    method: Mapped[str] = mapped_column(
        Enum("number", "coin", "time", name="method_enum"),
        nullable=False,
        comment="起卦方式：number=数字, coin=铜钱, time=时间"
    )

    numbers: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="起卦数字（JSON格式，数字起卦时使用）"
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        comment="起卦时间"
    )

    location: Mapped[str] = mapped_column(
        String(50),
        default="beijing",
        nullable=False,
        comment="起卦地点（用于真太阳时计算）"
    )

    solar_time: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否使用真太阳时"
    )

    # 卦象数据
    main_gua: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="本卦名称"
    )

    change_gua: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="变卦名称"
    )

    gua_type: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="卦类型（如：六冲卦、六合卦）"
    )

    shi_yao: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        nullable=True,
        comment="世爻位置（1-6）"
    )

    ying_yao: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        nullable=True,
        comment="应爻位置（1-6）"
    )

    lines: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="六爻详细数据（JSON格式）"
    )

    ganzhi: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="干支信息（年月日时）"
    )

    jiqi: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="节气信息"
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
        return f"<LiuyaoHexagram id={self.id} hexagram_id={self.hexagram_id} question={self.question[:20]}>"
