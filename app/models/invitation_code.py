from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    ForeignKey,
    UniqueConstraint,
    Index,
    SmallInteger,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvitationCode(Base):
    """
    邀请码表
    - 支持单次使用、多次使用、无限使用三种类型
    - 记录创建者和使用情况
    """
    __tablename__ = "invitation_codes"

    __table_args__ = (
        UniqueConstraint("code", name="uq_invitation_codes_code"),
        Index("ix_invitation_codes_status", "status"),
        Index("ix_invitation_codes_created_by", "created_by"),
    )

    # 主键
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="主键ID（自增）"
    )

    # 邀请码字符串（唯一，8-12位推荐）
    code: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="邀请码字符串（唯一）"
    )

    # 类型: single_use(单次), multi_use(多次), unlimited(无限)
    code_type: Mapped[str] = mapped_column(
        String(16),
        default="single_use",
        server_default=text("'single_use'"),
        nullable=False,
        comment="类型: single_use/multi_use/unlimited"
    )

    # 最大使用次数（0表示无限）
    max_uses: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
        comment="最大使用次数（0=无限）"
    )

    # 已使用次数
    used_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
        comment="已使用次数"
    )

    # 状态: 1=有效, 0=禁用, 2=过期/删除
    status: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        server_default=text("1"),
        nullable=False,
        comment="状态: 1=有效, 0=禁用, 2=过期"
    )

    # 过期时间（可选，null表示永不过期）
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="过期时间（null=永不过期）"
    )

    # 创建者（管理员用户ID）
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建者用户ID"
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
        return f"<InvitationCode id={self.id} code={self.code!r} used={self.used_count}/{self.max_uses}>"

    @property
    def is_valid(self) -> bool:
        """检查邀请码是否仍然有效"""
        if self.status != 1:
            return False
        if self.expires_at:
            now = datetime.now(timezone.utc)
            exp = self.expires_at.replace(tzinfo=timezone.utc) if self.expires_at.tzinfo is None else self.expires_at
            if now > exp:
                return False
        # 检查使用次数：max_uses 决定可用次数，0 表示无限
        if self.max_uses == 1 and self.used_count >= 1:
            return False
        if self.max_uses > 1 and self.used_count >= self.max_uses:
            return False
        return True


class InvitationCodeUsage(Base):
    """
    邀请码使用记录表
    - 记录每次邀请码的使用情况
    """
    __tablename__ = "invitation_code_usages"

    __table_args__ = (
        Index("ix_invitation_code_usages_code_id", "code_id"),
        Index("ix_invitation_code_usages_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="主键ID"
    )

    code_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("invitation_codes.id", ondelete="CASCADE"),
        nullable=False,
        comment="邀请码ID"
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="使用者用户ID"
    )

    used_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="使用时间"
    )

    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        comment="IP地址"
    )

    def __repr__(self) -> str:
        return f"<InvitationCodeUsage id={self.id} code_id={self.code_id} user_id={self.user_id}>"
