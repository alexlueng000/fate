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
    change_lines: Optional[dict]
    ganzhi: Optional[dict]
    jiqi: Optional[dict]
    shensha: Optional[str]
    gua_shen: Optional[str]
    lunar_date: Optional[str]
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
        change_lines={"lines": result.get("change_lines", [])},
        ganzhi=result.get("ganzhi"),
        jiqi=result.get("jieqi"),
        shensha=result.get("shensha"),
        gua_shen=result.get("gua_shen"),
        lunar_date=result.get("lunar_date"),
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


@router.post("/{hexagram_id}/interpret")
def interpret_hexagram(
    hexagram_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    AI解卦 - 流式输出
    """
    from fastapi.responses import StreamingResponse
    from app.chat.deepseek_client import call_deepseek_stream, set_caller
    from app.chat.sse import sse_pack
    from app.chat.rag import retrieve_kb

    # 查询卦象
    hexagram = db.query(LiuyaoHexagram).filter(
        LiuyaoHexagram.hexagram_id == hexagram_id,
        LiuyaoHexagram.user_id == current_user.id
    ).first()

    if not hexagram:
        raise HTTPException(status_code=404, detail="卦象不存在")

    # 提取动爻
    moving_lines = []
    if hexagram.lines and "lines" in hexagram.lines:
        for i, line in enumerate(hexagram.lines["lines"]):
            if line.get("is_dong"):
                moving_lines.append(i + 1)

    moving_lines_str = "、".join([f"第{n}爻" for n in moving_lines]) if moving_lines else "无动爻"

    # 检索六爻知识库
    kb_query = f"{hexagram.main_gua} {hexagram.change_gua or ''} {hexagram.question}"
    kb_passages = retrieve_kb(query=kb_query, kb_type="liuyao", k=5)
    kb_context = "\n\n".join(kb_passages) if kb_passages else "（知识库暂无相关内容）"

    # 性别显示
    gender_display = {"male": "男", "female": "女", "unknown": "未知"}.get(hexagram.gender, "未知")

    # 构建解卦prompt
    prompt = f"""你是一位精通《易经》的分析师，同时具备心理洞察与现实决策能力。

你的目标不是预测未来，而是帮助用户看清局势、识别问题，并做出更好的选择。

---

参考知识：
{kb_context}

---

输入：
- 问题：{hexagram.question}
- 性别：{gender_display}
- 本卦：{hexagram.main_gua}
- 变卦：{hexagram.change_gua or "无变卦"}
- 动爻：{moving_lines_str}

---

步骤一：识别真实问题

不要重复用户的问题。你需要判断：

- 用户真正焦虑的是什么
- 当前的核心不确定性在哪里
- 背后是决策问题，还是情绪问题

用一句话点出来，让用户有"被看穿"的感觉。

---

步骤二：卦象解读

说明：
- 本卦代表当前状态
- 变卦代表趋势变化
- 动爻代表关键转折（如有）

要求：具体、落地，不空泛

---

步骤三：底层模式识别

指出1-2个关键矛盾，例如：
- 想行动但犹豫
- 控制欲 vs 放手
- 短期收益 vs 长期稳定
- 外部压力 vs 内在抗拒

---

步骤四：行动建议

要求：
- 可执行
- 现实
- 不做绝对判断

避免：
- "一定会"
- "命中注定"

---

步骤五：收束总结

给一句让人"停下来想一秒"的总结，而不是鸡汤

---

输出结构：

### 1. 你真正面对的问题

### 2. 当前状态｜{hexagram.main_gua}

### 3. 发展趋势｜{hexagram.change_gua or "静卦"}

### 4. 核心矛盾

### 5. 行动建议

### 6. 一句话提醒

---

风格：
- 理性、克制
- 略带锋芒（不要太温柔）
- 像一个看透局势的人
- 不神叨，不空话"""

    messages = [{"role": "user", "content": prompt}]

    def generate():
        try:
            set_caller("liuyao_interpret")
            for chunk in call_deepseek_stream(messages):
                yield sse_pack({"text": chunk, "replace": False})
            yield sse_pack("[DONE]")
        except Exception as e:
            logger.error(f"解卦失败: {e}")
            yield sse_pack({"error": str(e)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
