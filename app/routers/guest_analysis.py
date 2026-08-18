from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.chat.deepseek_client import call_deepseek, set_caller
from app.db import get_db
from app.deps import get_current_user
from app.models import GuestAnalysis, User, UserProfile
from app.schemas.guest_analysis import (
    GuestAnalysisBindResponse,
    GuestAnalysisResponse,
    GuestAnalysisStartRequest,
)
from app.services.profile_service import ProfileService


router = APIRouter(prefix="/guest/analysis", tags=["guest-analysis"])

GUEST_ANALYSIS_PROMPT_VERSION = "guest_first_analysis_v2_card"
GUEST_ANALYSIS_TTL_DAYS = 7
GUEST_ANALYSIS_SESSION_LIMIT_HOURS = 24


def _client_ip(request: Request) -> Optional[str]:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:45]
    if request.client:
        return request.client.host[:45]
    return None


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = match.group(1) if match else text.strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _build_analysis_messages(analysis: GuestAnalysis, bazi_result: Dict[str, Any]) -> list[dict[str, str]]:
    payload = {
        "display_name": analysis.display_name,
        "gender": analysis.gender,
        "calendar_type": analysis.calendar_type,
        "birth_date": analysis.birth_date.isoformat(),
        "birth_time": analysis.birth_time.strftime("%H:%M:%S"),
        "birth_location": analysis.birth_location,
        "timezone": analysis.timezone,
        "bazi_result": bazi_result,
    }
    system_prompt = (
        "你是 FateInsight 的传统文化八字分析助手。"
        "请基于用户出生信息和排盘结果，生成首次个人分析，目标是在新用户前 5 分钟内让用户感到“这说的是我”。"
        "要求：语气温和、具体、有边界；不要做绝对化断言；不要提供医疗、法律、投资等高风险建议。"
        "输出必须完整但克制，避免长篇大论导致截断。overview 控制在 80 到 120 个中文字符；"
        "personality, career, relationship, wealth, current_phase 各控制在 120 到 180 个中文字符；"
        "每个字段都要独立完整，不要写“见上文”“后续展开”。"
        "只输出 JSON 对象，不要输出 Markdown。JSON 字段必须包含："
        "overview, personality, career, relationship, wealth, current_phase, suggestions。"
        "suggestions 是 3 到 5 个字符串数组，每条不超过 40 个中文字符。"
    )
    user_prompt = (
        "请为以下用户生成首次个人分析，适合展示在首次结果页：\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _ensure_guest_quota(db: Session, guest_session_id: str) -> None:
    cutoff = datetime.utcnow() - timedelta(hours=GUEST_ANALYSIS_SESSION_LIMIT_HOURS)
    existing = (
        db.query(GuestAnalysis)
        .filter(
            GuestAnalysis.guest_session_id == guest_session_id,
            GuestAnalysis.created_at >= cutoff,
            GuestAnalysis.status.in_(["running", "succeeded"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="游客每天只能生成一次免费首次分析",
        )


@router.post("/start", response_model=GuestAnalysisResponse, status_code=status.HTTP_201_CREATED)
def start_guest_analysis(
    data: GuestAnalysisStartRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _ensure_guest_quota(db, data.guest_session_id)

    now = datetime.utcnow()
    analysis = GuestAnalysis(
        public_id=str(uuid.uuid4()),
        guest_session_id=data.guest_session_id,
        status="running",
        display_name=data.display_name,
        gender=data.gender,
        calendar_type=data.calendar_type,
        birth_date=data.birth_date,
        birth_time=data.birth_time,
        birth_location=data.birth_location,
        birth_longitude=data.birth_longitude,
        birth_latitude=data.birth_latitude,
        timezone=data.timezone,
        prompt_version=GUEST_ANALYSIS_PROMPT_VERSION,
        request_ip=_client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
        expires_at=now + timedelta(days=GUEST_ANALYSIS_TTL_DAYS),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    bazi_result = ProfileService._calculate_bazi_chart(
        gender=data.gender,
        calendar_type=data.calendar_type,
        birth_date=data.birth_date,
        birth_time=data.birth_time,
        birth_location=data.birth_location,
        birth_longitude=data.birth_longitude,
        birth_latitude=data.birth_latitude,
    )
    if bazi_result.get("error"):
        analysis.status = "failed"
        analysis.error_message = str(bazi_result.get("error"))
        analysis.bazi_result = bazi_result
        db.commit()
        db.refresh(analysis)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=analysis.error_message)

    analysis.bazi_result = bazi_result
    db.commit()

    try:
        set_caller("guest_analysis_start")
        raw_reply = call_deepseek(_build_analysis_messages(analysis, bazi_result), thinking=False)
        parsed = _extract_json_object(raw_reply)
        analysis.analysis_result = parsed
        analysis.analysis_markdown = None if parsed else raw_reply
        analysis.status = "succeeded"
        analysis.error_message = None
    except Exception as exc:
        analysis.status = "failed"
        analysis.error_message = str(exc)[:1000]
        db.commit()
        db.refresh(analysis)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="首次分析生成失败，请稍后重试")

    db.commit()
    db.refresh(analysis)
    return analysis


@router.get("/{public_id}", response_model=GuestAnalysisResponse)
def get_guest_analysis(public_id: str, db: Session = Depends(get_db)):
    analysis = db.query(GuestAnalysis).filter(GuestAnalysis.public_id == public_id).first()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="游客分析不存在")

    if analysis.expires_at and analysis.expires_at < datetime.utcnow() and analysis.status != "expired":
        analysis.status = "expired"
        db.commit()
        db.refresh(analysis)

    return analysis


@router.post("/{public_id}/bind", response_model=GuestAnalysisBindResponse)
async def bind_guest_analysis(
    public_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(GuestAnalysis).filter(GuestAnalysis.public_id == public_id).first()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="游客分析不存在")
    if analysis.status == "expired":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="游客分析已过期")

    analysis.user_id = current_user.id
    analysis.bound_at = datetime.utcnow()

    existing_profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not existing_profile:
        ai_report = None
        if analysis.analysis_result:
            ai_report = json.dumps(analysis.analysis_result, ensure_ascii=False, indent=2)
        elif analysis.analysis_markdown:
            ai_report = analysis.analysis_markdown

        db.add(
            UserProfile(
                user_id=current_user.id,
                gender=analysis.gender,
                calendar_type=analysis.calendar_type,
                birth_date=analysis.birth_date,
                birth_time=analysis.birth_time,
                birth_location=analysis.birth_location,
                birth_longitude=analysis.birth_longitude,
                birth_latitude=analysis.birth_latitude,
                bazi_chart=analysis.bazi_result,
                ai_report=ai_report,
            )
        )

    db.commit()
    return GuestAnalysisBindResponse(ok=True, public_id=analysis.public_id, user_id=current_user.id)
