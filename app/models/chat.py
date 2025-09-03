# app/models/chat.py
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    DateTime,
    func,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base  # 你的 declarative_base()


MessageRole = Literal["user", "assistant", "system"]


class Conversation(Base):
    __tablename__ = "conversations"

    # 与 MySQL BIGINT UNSIGNED 对齐
    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="未命名会话",
    )

    # MySQL TIMESTAMP 无 tz；用 server_default/ onupdate 跟随数据库
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    # 关系
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.id.asc()",
    )

    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} user_id={self.user_id} title={self.title!r}>"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        nullable=False,
    )

    conversation_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    role: Mapped[MessageRole] = mapped_column(
        Enum("user", "assistant", "system", name="message_role"),
        nullable=False,
    )

    # MySQL MEDIUMTEXT；其他方言降级为 Text
    content: Mapped[str] = mapped_column(
        mysql.MEDIUMTEXT().with_variant(Text, "sqlite"),
        nullable=False,
    )

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
    )

    # 关系
    conversation: Mapped["Conversation"] = relationship(
        back_populates="messages",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_messages_conv_id_created", "conversation_id", "id"),
        Index("ix_messages_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Message id={self.id} conv_id={self.conversation_id} role={self.role}>"
