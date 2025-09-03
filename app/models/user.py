from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    Index,
    SmallInteger,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base  # 按你的项目路径调整
# from .order import Order
# from .entitlement import Entitlement
# from .user_identity import UserIdentity  # 如果你已经有该表，可解开注释


class User(Base):
    """
    用户主表（统一账户）
    - 既支持 Web（邮箱/密码/验证码）也支持小程序（微信 openid）登录的统一“人”。
    - openid 建议迁移到 user_identities 表，这里保留为可空字段以兼容历史逻辑。
    --- 
    """
    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("phone", name="uq_users_phone"),
        # openid 历史上是必填且唯一；迁移阶段将其改为可空并保留唯一约束（允许空值重复）
        UniqueConstraint("openid", name="uq_users_openid"),
        Index("ix_users_created_at", "created_at"),
    )

    # === 主键 ===
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="主键ID（自增）"
    )

    # === 历史字段：小程序 openid（建议迁移到 user_identities 表） ===
    openid: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,     # 兼容未来仅使用 user_identities 的情况
        index=True,
        comment="【兼容保留】微信小程序openId；建议迁移到 user_identities，保留以兼容老数据"
    )

    # === Web 登录相关字段（可为空，表示该用户未设置邮箱/密码） ===
    email: Mapped[Optional[str]] = mapped_column(
        String(254),
        nullable=True,
        index=True,
        comment="邮箱（Web 登录/通知）；可空；唯一约束见 uq_users_email"
    )

    username: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="用户名（Web 登录/通知）；可空；唯一约束见 uq_users_username"
    )

    phone: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        index=True,
        comment="手机号（可选，用于绑定/找回）；可空；唯一约束见 uq_users_phone"
    )

    password_hash: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="密码哈希（建议Argon2id），仅当用户设置了密码时存在；可空"
    )

    # === 展示信息 ===
    nickname: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="昵称（来源于注册时的昵称或微信头像昵称）"
    )

    avatar_url: Mapped[Optional[str]] = mapped_column(
        String(256),
        nullable=True,
        comment="头像URL（可选）"
    )

    # === 权限/状态 ===
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False
    )

    status: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,                  # 1=active, 0=blocked, 2=deleted (例)
        server_default=text("1"),
        nullable=False,
        comment="账户状态：1=active, 0=blocked, 2=deleted",
    )

    # 用户来源（统计/策略用，不影响鉴权逻辑）
    source: Mapped[Optional[str]] = mapped_column(
        String(16),
        nullable=True,
        comment="注册来源：web / miniapp / import 等（可选）"
    )

    locale: Mapped[Optional[str]] = mapped_column(
        String(8),
        nullable=True,
        comment="首选语言/区域（例如 zh-CN / en-US），用于UI提示等（可选）"
    )

    # === 时间信息 ===
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),   # 由数据库在插入时填充
        nullable=False,
        comment="创建时间（数据库当前时间）"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),   # 插入默认
        onupdate=func.now(),         # ORM层更新时写入
        nullable=False,
        comment="更新时间（记录最后一次资料变更时间）"
    )

    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="最近登录时间（登录成功后由服务端更新）"
    )

    last_login_ip: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        comment="最近登录IP（IPv4/IPv6），便于风控与审计（可选）"
    )

    # === 关联关系（便于反查） ===
    # orders: Mapped[List["Order"]] = relationship(
    #     back_populates="user",
    #     cascade="all,delete-orphan",
    #     passive_deletes=True,
    #     doc="用户的订单列表"
    # )

    # entitlements: Mapped[List["Entitlement"]] = relationship(
    #     back_populates="user",
    #     cascade="all,delete-orphan",
    #     passive_deletes=True,
    #     doc="用户的权益/订阅记录列表"
    # )

    # 如果你有独立的第三方身份表，建议开启这段关系
    # identities: Mapped[List["UserIdentity"]] = relationship(
    #     back_populates="user",
    #     cascade="all,delete-orphan",
    #     passive_deletes=True,
    #     doc="第三方身份集合（如 wechat_miniapp / github / email_otp 等）"
    # )

    # === 便捷属性/方法（非字段） ===
    @property
    def display_name(self) -> str:
        """用于前端展示的名称：优先昵称，其次邮箱/手机号/ID。"""
        return self.nickname or self.email or self.phone or f"用户{self.id}"

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} openid={bool(self.openid)} admin={self.is_admin}>"
