# app/models/api_call_log.py
"""
底层 API 调用日志 —— 与 DeepSeek 后台对账用。
不依赖 user_id，每一次 HTTP 请求（含重试）都记一条。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Index,
    Integer,
    String,
    DateTime,
    Boolean,
    Float,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT as UBIGINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ApiCallLog(Base):
    __tablename__ = "api_call_logs"

    id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
    )

    # 模型名称: deepseek-chat, deepseek-reasoner 等
    model: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="模型名称",
    )

    # 调用方标识: chat_start, chat_send, simplify, ws_start, ws_send 等
    caller: Mapped[str] = mapped_column(
        String(64), nullable=False, default="unknown", comment="调用来源",
    )

    # 是否流式请求
    stream: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否流式",
    )

    # Token 统计（非流式可从响应拿到，流式填 0）
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="输入 token",
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="输出 token",
    )

    # 缓存统计（DeepSeek Context Caching）
    prompt_cache_hit_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="缓存命中 token (0.1元/百万)",
    )
    prompt_cache_miss_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="缓存未命中 token (1元/百万)",
    )

    # 耗时（秒）
    latency: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="请求耗时(秒)",
    )

    # 是否成功
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否成功",
    )

    # 重试次序: 0=首次, 1=第一次重试, 2=第二次重试
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="重试次序(0=首次)",
    )

    # 错误信息（失败时记录）
    error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="错误信息",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_api_call_logs_created", "created_at"),
        Index("ix_api_call_logs_model", "model"),
        Index("ix_api_call_logs_caller", "caller"),
    )

    def __repr__(self) -> str:
        return f"<ApiCallLog id={self.id} model={self.model} caller={self.caller}>"
