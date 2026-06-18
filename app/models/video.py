from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import BIGINT as UBIGINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class VideoCourse(Base):
    __tablename__ = "video_courses"

    id: Mapped[int] = mapped_column(UBIGINT(unsigned=True), primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    subtitle: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lessons: Mapped[list["VideoLesson"]] = relationship(
        "VideoLesson", back_populates="course", cascade="all,delete-orphan", passive_deletes=True
    )


class VideoLesson(Base):
    __tablename__ = "video_lessons"
    __table_args__ = (UniqueConstraint("course_id", "slug", name="uk_video_lessons_course_slug"),)

    id: Mapped[int] = mapped_column(UBIGINT(unsigned=True), primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True), ForeignKey("video_courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    access_level: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    provider: Mapped[str] = mapped_column(String(20), default="vod", nullable=False)
    provider_video_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    course: Mapped[VideoCourse] = relationship("VideoCourse", back_populates="lessons")
    progress: Mapped[list["VideoWatchProgress"]] = relationship(
        "VideoWatchProgress", back_populates="lesson", cascade="all,delete-orphan", passive_deletes=True
    )


class VideoWatchProgress(Base):
    __tablename__ = "video_watch_progress"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uk_video_watch_progress_user_lesson"),)

    id: Mapped[int] = mapped_column(UBIGINT(unsigned=True), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    lesson_id: Mapped[int] = mapped_column(
        UBIGINT(unsigned=True), ForeignKey("video_lessons.id", ondelete="CASCADE"), index=True, nullable=False
    )
    last_position_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_watched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # type: ignore[name-defined]
    lesson: Mapped[VideoLesson] = relationship("VideoLesson", back_populates="progress")
