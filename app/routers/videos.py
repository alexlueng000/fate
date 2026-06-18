from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db, get_db_tx
from app.deps import get_current_user, get_current_user_optional
from app.models import User
from app.schemas import VideoCourseOut, VideoLessonOut, VideoPlayOut, VideoProgressIn, VideoProgressOut
from app.services import video_service

router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("/courses", response_model=list[VideoCourseOut])
def list_video_courses(db: Session = Depends(get_db)) -> list[VideoCourseOut]:
    return video_service.list_courses(db)


@router.get("/courses/{course_id}", response_model=VideoCourseOut)
def get_video_course(course_id: int, db: Session = Depends(get_db)) -> VideoCourseOut:
    course = video_service.get_course(db, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


@router.get("/lessons/{lesson_id}", response_model=VideoLessonOut)
def get_video_lesson(lesson_id: int, db: Session = Depends(get_db)) -> VideoLessonOut:
    lesson = video_service.get_lesson(db, lesson_id)
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")
    return lesson


@router.post("/lessons/{lesson_id}/play", response_model=VideoPlayOut)
async def play_video_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> VideoPlayOut:
    lesson = video_service.get_lesson(db, lesson_id)
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")

    allowed, reason = video_service.can_play_lesson(db, lesson=lesson, user=current_user)
    if not allowed and reason == "UNAUTHENTICATED":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=reason)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    play_url = video_service.get_play_url(lesson)
    if not play_url:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="VIDEO_SOURCE_NOT_CONFIGURED")

    return VideoPlayOut(lesson_id=lesson.id, play_url=play_url, provider=lesson.provider)


@router.post("/lessons/{lesson_id}/progress", response_model=VideoProgressOut)
def update_video_progress(
    lesson_id: int,
    body: VideoProgressIn,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user),
) -> VideoProgressOut:
    lesson = video_service.get_lesson(db, lesson_id)
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")

    progress = video_service.upsert_progress(
        db,
        user_id=current_user.id,
        lesson_id=lesson_id,
        position_seconds=body.position_seconds,
        completed=body.completed,
    )
    return progress
