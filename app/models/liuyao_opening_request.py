"""One durable opening request for each owned hexagram."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class LiuyaoOpeningRequest(Base):
    __tablename__ = 'liuyao_opening_requests'
    hexagram_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('liuyao_hexagrams.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(32), unique=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey('conversations.id', ondelete='CASCADE'), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
