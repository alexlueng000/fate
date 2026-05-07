# app/models/product.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer,
    String,
    Boolean,
    DateTime,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Product(Base):
    """
    商品表 - 提问次数包
    """
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        nullable=False,
    )

    # 商品编码，如 chat_5, chat_20
    code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
        comment="商品编码",
    )

    # 商品名称
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="商品名称",
    )

    # 价格（分为单位）
    price_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="价格（分）",
    )

    # 币种
    currency: Mapped[str] = mapped_column(
        String(8),
        default="CNY",
        nullable=False,
        comment="币种",
    )

    # 提供的次数
    quota_amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="提供的提问次数",
    )

    # 八字解读次数（套餐拆分后使用，单独从 quota_type='chat' 扣减）
    bazi_quota: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="八字次数（quota_type=chat）",
    )

    # 六爻问卦次数（quota_type='liuyao_chat'）
    liuyao_quota: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="六爻次数（quota_type=liuyao_chat）",
    )

    # 描述
    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="商品描述",
    )

    # 是否在售
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否在售",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )
