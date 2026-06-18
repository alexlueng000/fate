from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import User, VideoCourse, VideoLesson, VideoWatchProgress
from app.services.membership_service import has_video_access


def list_courses(db: Session) -> list[VideoCourse]:
    stmt = (
        select(VideoCourse)
        .where(VideoCourse.is_active.is_(True))
        .options(selectinload(VideoCourse.lessons))
        .order_by(VideoCourse.sort_order.asc(), VideoCourse.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def get_course(db: Session, course_id: int) -> Optional[VideoCourse]:
    stmt = (
        select(VideoCourse)
        .where(VideoCourse.id == course_id, VideoCourse.is_active.is_(True))
        .options(selectinload(VideoCourse.lessons))
    )
    return db.execute(stmt).scalars().first()


def get_lesson(db: Session, lesson_id: int) -> Optional[VideoLesson]:
    stmt = select(VideoLesson).where(VideoLesson.id == lesson_id, VideoLesson.is_active.is_(True))
    return db.execute(stmt).scalars().first()


def can_play_lesson(db: Session, *, lesson: VideoLesson, user: Optional[User]) -> tuple[bool, str]:
    if lesson.access_level == "free":
        return True, "OK"
    if not user:
        return False, "UNAUTHENTICATED"
    if not has_video_access(db, user.id):
        return False, "MEMBERSHIP_REQUIRED"
    return True, "OK"


def get_play_url(lesson: VideoLesson) -> Optional[str]:
    return lesson.source_url


def upsert_progress(
    db: Session,
    *,
    user_id: int,
    lesson_id: int,
    position_seconds: int,
    completed: bool,
) -> VideoWatchProgress:
    stmt = select(VideoWatchProgress).where(
        VideoWatchProgress.user_id == user_id,
        VideoWatchProgress.lesson_id == lesson_id,
    )
    progress = db.execute(stmt).scalars().first()
    if not progress:
        progress = VideoWatchProgress(user_id=user_id, lesson_id=lesson_id)
        db.add(progress)

    progress.last_position_seconds = max(0, position_seconds)
    progress.completed = completed
    progress.last_watched_at = datetime.utcnow()
    db.flush()
    return progress
