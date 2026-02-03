"""
密码重置验证码模型
- 存储邮箱验证码及其状态
- 支持频率限制和失败次数追踪
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Boolean,
    Index,
    SmallInteger,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PasswordResetCode(Base):
    """密码重置验证码表"""
    __tablename__ = "password_reset_codes"

    __table_args__ = (
        Index("ix_password_reset_codes_email", "email"),
        Index("ix_password_reset_codes_created_at", "created_at"),
    )

    # 主键
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="主键ID（自增）"
    )

    # 邮箱（不设唯一约束，允许多条记录）
    email: Mapped[str] = mapped_column(
        String(254),
        nullable=False,
        comment="用户邮箱"
    )

    # 6位数字验证码
    code: Mapped[str] = mapped_column(
        String(6),
        nullable=False,
        comment="6位数字验证码"
    )

    # 是否已使用
    is_used: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("0"),
        nullable=False,
        comment="是否已使用"
    )

    # 验证失败次数
    failed_attempts: Mapped[int] = mapped_column(
        SmallInteger,
        default=0,
        server_default=text("0"),
        nullable=False,
        comment="验证失败次数"
    )

    # 过期时间
    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        comment="过期时间"
    )

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间"
    )

    # IP地址（用于审计）
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        comment="请求IP地址"
    )

    def __repr__(self) -> str:
        return f"<PasswordResetCode id={self.id} email={self.email!r} used={self.is_used}>"
