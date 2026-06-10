# app/routers/relationship_progress.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user_or_401
from app.models.relationship_progress import RelationshipProgress

router = APIRouter(prefix="/relationship-progress", tags=["relationship-progress"])


class RelationshipProgressCreate(BaseModel):
    task_id: Optional[str] = Field(default=None, max_length=128)
    task_context: Dict[str, Any]
    content: str = Field(min_length=1, max_length=5000)
    review_due_at: Optional[datetime] = None


class RelationshipReviewUpdate(BaseModel):
    task_id: Optional[str] = Field(default=None, max_length=128)
    task_context: Dict[str, Any]
    review_due_at: datetime


class RelationshipProgressResponse(BaseModel):
    id: int
    task_id: Optional[str]
    task_context: Dict[str, Any]
    content: Optional[str]
    review_due_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = dict(from_attributes=True)


def _validate_task_context(task_context: Dict[str, Any]) -> None:
    if task_context.get("taskType") != "relationship":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task_context must be a relationship task",
        )


def _to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/latest", response_model=Optional[RelationshipProgressResponse])
def get_latest_relationship_progress(
    user_id: int = Depends(get_current_user_or_401),
    db: Session = Depends(get_db),
):
    return (
        db.query(RelationshipProgress)
        .filter(RelationshipProgress.user_id == user_id)
        .order_by(desc(RelationshipProgress.updated_at), desc(RelationshipProgress.id))
        .first()
    )


@router.post("", response_model=RelationshipProgressResponse, status_code=status.HTTP_201_CREATED)
def create_relationship_progress(
    data: RelationshipProgressCreate,
    user_id: int = Depends(get_current_user_or_401),
    db: Session = Depends(get_db),
):
    _validate_task_context(data.task_context)
    record = RelationshipProgress(
        user_id=user_id,
        task_id=data.task_id,
        task_context=data.task_context,
        content=data.content.strip(),
        review_due_at=_to_naive_utc(data.review_due_at),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.post("/review", response_model=RelationshipProgressResponse, status_code=status.HTTP_201_CREATED)
def create_relationship_review_reminder(
    data: RelationshipReviewUpdate,
    user_id: int = Depends(get_current_user_or_401),
    db: Session = Depends(get_db),
):
    _validate_task_context(data.task_context)
    record = RelationshipProgress(
        user_id=user_id,
        task_id=data.task_id,
        task_context=data.task_context,
        content=None,
        review_due_at=_to_naive_utc(data.review_due_at),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
