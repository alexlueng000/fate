"""One recoverable first-report generation per profile."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import INTEGER
from app.db import Base


class PersonalReportRequest(Base):
    __tablename__ = 'personal_report_requests'
    profile_id: Mapped[int] = mapped_column(INTEGER(unsigned=True), ForeignKey('user_profiles.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, index=True)
    chart_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    token: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    lease_until: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
