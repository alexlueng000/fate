# app/routers/liuyao.py
"""
六爻玄机 API 路由
提供排盘、AI解卦、历史记录等功能
"""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..db import get_db, get_db_tx
from ..deps import get_current_user
from ..models import User
from ..models.liuyao import LiuyaoHexagram
from app.liuyao.paipan import LiuyaoPaipan
from app.core.logging import get_logger
import json

logger = get_logger("liuyao.router")
router = APIRouter(prefix="/liuyao", tags=["liuyao"])


# ==================== Pydantic Schemas ====================
from pydantic import BaseModel, Field


class PaipanRequest(BaseModel):
    """排盘请求"""
    question: str = Field(..., min_length=1, max_length=500, description="问事内容")
    gender: str = Field(default="unknown", description="性别：male/female/unknown")
    method: str = Field(..., description="起卦方式：number/coin/time")
    numbers: Optional[List[int]] = Field(None, description="数字起卦的三个数字")
    timestamp: Optional[str] = Field(None, description="起卦时间（ISO格式）")
    location: str = Field(default="beijing", description="起卦地点")
    solar_time: bool = Field(default=True, description="是否使用真太阳时")


class HexagramResponse(BaseModel):
    """卦象响应"""
    id: int
    hexagram_id: str
    question: str
    gender: str
    method: str
    main_gua: str
    change_gua: Optional[str]
    shi_yao: Optional[int]
    ying_yao: Optional[int]
    lines: Optional[dict]
    ganzhi: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True


class HexagramDetailResponse(BaseModel):
    """卦象详情响应（包含完整数据）"""
    id: int
    hexagram_id: str
    question: str
    gender: str
    method: str
    numbers: Optional[dict]
    timestamp: datetime
    location: str
    solar_time: bool
    main_gua: Optional[str]
    change_gua: Optional[str]
    gua_type: Optional[str]
    shi_yao: Optional[int]
    ying_yao: Optional[int]
    lines: Optional[dict]
    ganzhi: Optional[dict]
    jiqi: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== API Endpoints ====================

@router.post("/paipan", response_model=HexagramDetailResponse)
def create_paipan(
    req: PaipanRequest,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user)
):
    """
    六爻排盘

    根据用户输入的问事和起卦方式，生成卦象
    """
    # 验证起卦方式
    if req.method not in ["number", "coin", "time"]:
        raise HTTPException(status_code=400, detail="起卦方式必须是 number/coin/time")

    # 数字起卦需要提供3个数字
    if req.method == "number" and (not req.numbers or len(req.numbers) != 3):
        raise HTTPException(status_code=400, detail="数字起卦需要提供3个数字")

    # 解析时间
    timestamp = datetime.fromisoformat(req.timestamp) if req.timestamp else datetime.now()

    # 执行排盘
    try:
        paipan = LiuyaoPaipan(
            question=req.question,
            method=req.method,
            gender=req.gender,
            timestamp=timestamp,
            location=req.location,
            solar_time=req.solar_time,
            numbers=req.numbers,
        )
        result = paipan.calc()
    except Exception as e:
        logger.error(f"排盘失败: {e}")
        raise HTTPException(status_code=500, detail=f"排盘失败: {str(e)}")

    # 保存到数据库
    hexagram = LiuyaoHexagram(
        user_id=current_user.id,
        hexagram_id=result["hexagram_id"],
        question=req.question,
        gender=req.gender,
        method=req.method,
        numbers={"numbers": req.numbers} if req.numbers else None,
        timestamp=timestamp,
        location=req.location,
        solar_time=req.solar_time,
        main_gua=result.get("main_gua"),
        change_gua=result.get("change_gua"),
        gua_type=None,  # 可以后续扩展
        shi_yao=result.get("shi_yao"),
        ying_yao=result.get("ying_yao"),
        lines={"lines": result.get("lines", [])},
        ganzhi=result.get("ganzhi"),
        jiqi=None,  # 可以后续扩展
    )

    db.add(hexagram)
    db.flush()

    return HexagramDetailResponse.model_validate(hexagram)


@router.get("/history", response_model=List[HexagramResponse])
def get_history(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取用户的六爻历史记录
    """
    hexagrams = db.query(LiuyaoHexagram).filter(
        LiuyaoHexagram.user_id == current_user.id
    ).order_by(desc(LiuyaoHexagram.created_at)).limit(limit).offset(offset).all()

    return [HexagramResponse.model_validate(h) for h in hexagrams]


@router.get("/{hexagram_id}", response_model=HexagramDetailResponse)
def get_hexagram(
    hexagram_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取单个卦象详情
    """
    hexagram = db.query(LiuyaoHexagram).filter(
        LiuyaoHexagram.hexagram_id == hexagram_id,
        LiuyaoHexagram.user_id == current_user.id
    ).first()

    if not hexagram:
        raise HTTPException(status_code=404, detail="卦象不存在")

    return HexagramDetailResponse.model_validate(hexagram)


@router.delete("/{hexagram_id}")
def delete_hexagram(
    hexagram_id: str,
    db: Session = Depends(get_db_tx),
    current_user: User = Depends(get_current_user)
):
    """
    删除卦象记录
    """
    hexagram = db.query(LiuyaoHexagram).filter(
        LiuyaoHexagram.hexagram_id == hexagram_id,
        LiuyaoHexagram.user_id == current_user.id
    ).first()

    if not hexagram:
        raise HTTPException(status_code=404, detail="卦象不存在")

    db.delete(hexagram)
    db.flush()

    return {"success": True, "hexagram_id": hexagram_id}


@router.get("/stats/count")
def get_hexagram_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取用户的卦象总数
    """
    count = db.query(LiuyaoHexagram).filter(
        LiuyaoHexagram.user_id == current_user.id
    ).count()

    return {"count": count}
