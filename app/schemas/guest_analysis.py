from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class GuestAnalysisStartRequest(BaseModel):
    guest_session_id: str = Field(..., min_length=8, max_length=64)
    display_name: Optional[str] = Field(None, max_length=64)
    gender: Literal["male", "female"]
    calendar_type: Literal["solar", "lunar"] = "solar"
    birth_date: date
    birth_time: time
    birth_location: str = Field(..., min_length=1, max_length=100)
    birth_longitude: Optional[float] = Field(None, ge=-180, le=180)
    birth_latitude: Optional[float] = Field(None, ge=-90, le=90)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)

    @field_validator("guest_session_id")
    @classmethod
    def validate_guest_session_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("guest_session_id is required")
        return value

    @field_validator("display_name", "birth_location", "timezone")
    @classmethod
    def trim_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class GuestAnalysisResponse(BaseModel):
    public_id: str
    guest_session_id: str
    user_id: Optional[int]
    status: str
    error_message: Optional[str]
    display_name: Optional[str]
    gender: str
    calendar_type: str
    birth_date: date
    birth_time: time
    birth_location: str
    birth_longitude: Optional[float]
    birth_latitude: Optional[float]
    timezone: str
    bazi_result: Optional[Dict[str, Any]]
    analysis_result: Optional[Dict[str, Any]]
    analysis_markdown: Optional[str]
    prompt_version: Optional[str]
    bound_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GuestAnalysisBindResponse(BaseModel):
    ok: bool
    public_id: str
    user_id: int
