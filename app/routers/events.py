# app/routers/events.py
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user_optional
from app.models import User
from app.models.user_event import UserEvent

router = APIRouter(prefix="/events", tags=["events"])

MAX_PAYLOAD_BYTES = 4096


class TrackEventRequest(BaseModel):
    event_name: str = Field(min_length=1, max_length=80)
    event_source: Optional[str] = Field(default=None, max_length=40)
    page_path: Optional[str] = Field(default=None, max_length=255)
    payload: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = Field(default=None, max_length=80)


class TrackEventResponse(BaseModel):
    ok: bool
    id: int
    created_at: datetime


def _validate_payload(payload: Optional[Dict[str, Any]]) -> None:
    if payload is None:
        return
    try:
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payload must be JSON serializable",
        )
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="payload is too large",
        )


@router.post("/track", response_model=TrackEventResponse, status_code=status.HTTP_201_CREATED)
async def track_event(
    data: TrackEventRequest,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    _validate_payload(data.payload)
    record = UserEvent(
        user_id=current_user.id if current_user else None,
        event_name=data.event_name,
        event_source=data.event_source or "web",
        page_path=data.page_path,
        payload=data.payload,
        session_id=data.session_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return TrackEventResponse(ok=True, id=record.id, created_at=record.created_at)
