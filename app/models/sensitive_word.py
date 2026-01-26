from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    SmallInteger,
    Boolean,
    Index,
    UniqueConstraint,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SensitiveWord(Base):
    """
    敏感词表
    - 用于过滤 AI 响应中的敏感词汇
    - 支持普通替换和正则替换
    """
    __tablename__ = "sensitive_words"

    __table_args__ = (
        UniqueConstraint("word", name="uq_sensitive_words_word"),
        Index("ix_sensitive_words_status", "status"),
        Index("ix_sensitive_words_priority", "priority"),
        Index("ix_sensitive_words_category", "category"),
    )

    # 主键
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="主键ID（自增）"
    )

    # 敏感词
    word: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="敏感词"
    )

    # 替换词
    replacement: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="替换词"
    )

    # 分类
    category: Mapped[str] = mapped_column(
        String(32),
        default="general",
        server_default=text("'general'"),
        nullable=False,
        comment="分类: general/术语/迷信/确定性/冲突/功利"
    )

    # 是否正则匹配
    is_regex: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("0"),
        nullable=False,
        comment="是否正则匹配"
    )

    # 优先级（数字越大越先匹配）
    priority: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
        comment="优先级（越大越先匹配）"
    )

    # 状态: 1=启用, 0=禁用
    status: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        server_default=text("1"),
        nullable=False,
        comment="状态: 1=启用, 0=禁用"
    )

    # 备注
    note: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="备注"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间"
    )

    def __repr__(self) -> str:
        return f"<SensitiveWord id={self.id} word={self.word!r} -> {self.replacement!r}>"
