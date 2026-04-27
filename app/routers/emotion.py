# app/routers/emotion.py
"""
心镜灯（Emotional Mirror）API 路由
提供情绪记录、例外时刻、价值行动等功能
"""
from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from ..db import get_db, get_db_tx
from ..deps import get_current_user
from ..models import User
from ..models.emotion import EmotionRecord, ExceptionMoment, ValueAction
from ..models.profile import UserProfile
from ..utils.solar_terms import get_solar_term, get_term_description
from ..utils.wuxing_analysis import (
    analyze_bazi_wuxing,
    get_character_profile,
    get_emotion_guidance,
    extract_bazi_from_profile
)
from app.core.logging import get_logger
import json

logger = get_logger("emotion.router")
router = APIRouter(prefix="/emotion", tags=["emotion"])


# ==================== Pydantic Schemas ====================
from pydantic import BaseModel, Field


class EmotionRecordCreate(BaseModel):
    """创建情绪记录请求"""
    emotion_score: int = Field(..., ge=1, le=10, description="情绪评分 1-10")
    emotion_tags: Optional[List[str]] = Field(None, description="情绪标签")
    content: str = Field(..., min_length=1, max_length=5000, description="情绪记录内容")


class EmotionRecordResponse(BaseModel):
    """情绪记录响应"""
    id: int
    user_id: int
    record_date: datetime
    solar_term: Optional[str]
    wuxing_element: Optional[str]
    emotion_score: int
    emotion_tags: Optional[List[str]]
    content: str
    ai_response: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class WeeklyChartResponse(BaseModel):
    """一周情绪图表响应"""
    dates: List[str]
    scores: List[Optional[int]]
    average_score: float


class CharacterProfileResponse(BaseModel):
    """性格档案响应"""
    element: str
    positive_traits: List[str]
    negative_traits: List[str]
    emotion_tendency: str
    advice: str
    wuxing_balance: dict


class ExceptionMomentCreate(BaseModel):
    """创建例外时刻请求"""
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=5000)
    moment_date: datetime


class ExceptionMomentResponse(BaseModel):
    """例外时刻响应"""
    id: int
    user_id: int
    title: str
    content: str
    moment_date: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class ValueActionCreate(BaseModel):
    """创建价值行动请求"""
    value_name: str = Field(..., min_length=1, max_length=128)
    action_plan: str = Field(..., min_length=1, max_length=5000)


class ValueActionResponse(BaseModel):
    """价值行动响应"""
    id: int
    user_id: int
    value_name: str
    action_plan: str
    status: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==================== API Endpoints ====================

@router.post("/records", response_model=EmotionRecordResponse)
def create_emotion_record(
    req: EmotionRecordCreate,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user)
):
    """
    创建今日情绪记录
    """
    # 获取当前日期的节气和五行
    now = datetime.now()
    solar_term, wuxing = get_solar_term(now)

    # 创建情绪记录
    record = EmotionRecord(
        user_id=current_user.id,
        record_date=now,
        solar_term=solar_term,
        wuxing_element=wuxing,
        emotion_score=req.emotion_score,
        emotion_tags=json.dumps(req.emotion_tags, ensure_ascii=False) if req.emotion_tags else None,
        content=req.content,
        ai_response=None  # AI响应将通过流式接口生成
    )

    db.add(record)
    db.flush()

    # 手动构建响应，解析 JSON 字段
    return EmotionRecordResponse(
        id=record.id,
        user_id=record.user_id,
        record_date=record.record_date,
        solar_term=record.solar_term,
        wuxing_element=record.wuxing_element,
        emotion_score=record.emotion_score,
        emotion_tags=json.loads(record.emotion_tags) if record.emotion_tags else None,
        content=record.content,
        ai_response=record.ai_response,
        created_at=record.created_at
    )


@router.get("/records", response_model=List[EmotionRecordResponse])
def get_emotion_records(
    limit: int = 30,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取用户的情绪记录列表
    """
    records = db.query(EmotionRecord).filter(
        EmotionRecord.user_id == current_user.id
    ).order_by(desc(EmotionRecord.record_date)).limit(limit).offset(offset).all()

    # 手动构建响应列表，解析 JSON 字段
    result = []
    for record in records:
        result.append(EmotionRecordResponse(
            id=record.id,
            user_id=record.user_id,
            record_date=record.record_date,
            solar_term=record.solar_term,
            wuxing_element=record.wuxing_element,
            emotion_score=record.emotion_score,
            emotion_tags=json.loads(record.emotion_tags) if record.emotion_tags else None,
            content=record.content,
            ai_response=record.ai_response,
            created_at=record.created_at
        ))

    return result


@router.get("/records/{record_id}", response_model=EmotionRecordResponse)
def get_emotion_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取单条情绪记录详情
    """
    record = db.query(EmotionRecord).filter(
        EmotionRecord.id == record_id,
        EmotionRecord.user_id == current_user.id
    ).first()

    if not record:
        raise HTTPException(status_code=404, detail="情绪记录不存在")

    # 手动构建响应，解析 JSON 字段
    return EmotionRecordResponse(
        id=record.id,
        user_id=record.user_id,
        record_date=record.record_date,
        solar_term=record.solar_term,
        wuxing_element=record.wuxing_element,
        emotion_score=record.emotion_score,
        emotion_tags=json.loads(record.emotion_tags) if record.emotion_tags else None,
        content=record.content,
        ai_response=record.ai_response,
        created_at=record.created_at
    )


@router.get("/weekly-chart", response_model=WeeklyChartResponse)
def get_weekly_chart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取最近7天的情绪图表数据
    """
    today = datetime.now().date()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

    # 查询最近7天的记录
    records = db.query(EmotionRecord).filter(
        EmotionRecord.user_id == current_user.id,
        func.date(EmotionRecord.record_date) >= today - timedelta(days=6)
    ).all()

    # 构建日期到分数的映射
    date_score_map = {}
    for record in records:
        date_str = record.record_date.strftime("%Y-%m-%d")
        date_score_map[date_str] = record.emotion_score

    # 构建响应数据
    scores = [date_score_map.get(date) for date in dates]
    valid_scores = [s for s in scores if s is not None]
    average_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0

    return WeeklyChartResponse(
        dates=dates,
        scores=scores,
        average_score=round(average_score, 2)
    )


@router.get("/character-profile", response_model=CharacterProfileResponse)
def get_character_profile_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取用户的性格档案（基于八字五行分析）
    """
    # 获取用户的八字档案
    profile = db.query(UserProfile).filter(
        UserProfile.user_id == current_user.id
    ).first()

    if not profile or not profile.bazi_data:
        raise HTTPException(
            status_code=404,
            detail="未找到八字档案，请先完成八字测算"
        )

    # 解析八字数据
    try:
        bazi_data = json.loads(profile.bazi_data) if isinstance(profile.bazi_data, str) else profile.bazi_data
    except:
        raise HTTPException(status_code=500, detail="八字数据格式错误")

    # 分析五行
    wuxing_analysis = analyze_bazi_wuxing(bazi_data)
    strongest_element = wuxing_analysis.get("strongest", "土")

    # 获取性格档案
    character_profile = get_character_profile(strongest_element)

    return CharacterProfileResponse(
        element=character_profile["element"],
        positive_traits=character_profile["positive_traits"],
        negative_traits=character_profile["negative_traits"],
        emotion_tendency=character_profile["emotion_tendency"],
        advice=character_profile["advice"],
        wuxing_balance=wuxing_analysis
    )


@router.post("/exception-moments", response_model=ExceptionMomentResponse)
def create_exception_moment(
    req: ExceptionMomentCreate,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user)
):
    """
    创建例外时刻记录
    """
    moment = ExceptionMoment(
        user_id=current_user.id,
        title=req.title,
        content=req.content,
        moment_date=req.moment_date
    )

    db.add(moment)
    db.flush()

    return ExceptionMomentResponse.model_validate(moment)


@router.get("/exception-moments", response_model=List[ExceptionMomentResponse])
def get_exception_moments(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取用户的例外时刻列表
    """
    moments = db.query(ExceptionMoment).filter(
        ExceptionMoment.user_id == current_user.id
    ).order_by(desc(ExceptionMoment.moment_date)).limit(limit).offset(offset).all()

    return [ExceptionMomentResponse.model_validate(m) for m in moments]


@router.post("/value-actions", response_model=ValueActionResponse)
def create_value_action(
    req: ValueActionCreate,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user)
):
    """
    创建价值行动计划
    """
    action = ValueAction(
        user_id=current_user.id,
        value_name=req.value_name,
        action_plan=req.action_plan,
        status=0  # 计划中
    )

    db.add(action)
    db.flush()

    return ValueActionResponse.model_validate(action)


@router.get("/value-actions", response_model=List[ValueActionResponse])
def get_value_actions(
    status: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取用户的价值行动列表
    """
    query = db.query(ValueAction).filter(ValueAction.user_id == current_user.id)

    if status is not None:
        query = query.filter(ValueAction.status == status)

    actions = query.order_by(desc(ValueAction.created_at)).limit(limit).offset(offset).all()

    return [ValueActionResponse.model_validate(a) for a in actions]


@router.patch("/value-actions/{action_id}/status")
def update_value_action_status(
    action_id: int,
    status: int,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user)
):
    """
    更新价值行动状态
    0=计划中, 1=进行中, 2=已完成

    Args:
        action_id: 价值行动ID
        status: 状态值 (0-2)
    """
    if status < 0 or status > 2:
        raise HTTPException(status_code=400, detail="状态值必须在0-2之间")

    action = db.query(ValueAction).filter(
        ValueAction.id == action_id,
        ValueAction.user_id == current_user.id
    ).first()

    if not action:
        raise HTTPException(status_code=404, detail="价值行动不存在")

    action.status = status
    db.flush()

    return {"success": True, "action_id": action_id, "status": status}
