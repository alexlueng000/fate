# app/routers/admin_stats.py
"""
管理后台统计分析 API

提供以下统计数据：
- 总览统计（用户数、对话数、消息数、反馈数）
- 用户注册趋势
- 用户来源分布
- 对话趋势
- 用户配额管理
- 用户使用排行榜
"""
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, text, desc
from sqlalchemy.orm import Session

from app.db import get_db, get_db_tx
from app.deps import get_admin_user
from app.models import User
from app.models.chat import Conversation, Message
from app.models.feedback import Feedback
from app.models.quota import UserQuota
from app.models.usage_log import UsageLog
from app.services.quota import QuotaService
from app.core.logging import get_logger

logger = get_logger("admin.stats")
router = APIRouter(prefix="/admin/stats", tags=["admin-stats"])


@router.get("/overview")
async def get_overview(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user)
):
    """获取总览统计数据"""
    logger.info("get_overview_request")

    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # 用户统计
    total_users = db.query(func.count(User.id)).scalar() or 0
    today_users = db.query(func.count(User.id)).filter(
        func.date(User.created_at) == today
    ).scalar() or 0
    week_users = db.query(func.count(User.id)).filter(
        func.date(User.created_at) >= week_ago
    ).scalar() or 0
    month_users = db.query(func.count(User.id)).filter(
        func.date(User.created_at) >= month_ago
    ).scalar() or 0

    # 活跃用户（7天内有登录）
    active_users = db.query(func.count(User.id)).filter(
        User.last_login_at >= datetime.now() - timedelta(days=7)
    ).scalar() or 0

    # 对话统计
    total_conversations = db.query(func.count(Conversation.id)).scalar() or 0
    today_conversations = db.query(func.count(Conversation.id)).filter(
        func.date(Conversation.created_at) == today
    ).scalar() or 0

    # 消息统计
    total_messages = db.query(func.count(Message.id)).scalar() or 0
    tokens_result = db.query(
        func.sum(Message.prompt_tokens),
        func.sum(Message.completion_tokens)
    ).first()
    total_prompt_tokens = tokens_result[0] or 0
    total_completion_tokens = tokens_result[1] or 0

    # 反馈统计
    pending_feedbacks = db.query(func.count(Feedback.id)).filter(
        Feedback.status == "pending"
    ).scalar() or 0

    return {
        "users": {
            "total": total_users,
            "today": today_users,
            "this_week": week_users,
            "this_month": month_users,
            "active_7d": active_users
        },
        "conversations": {
            "total": total_conversations,
            "today": today_conversations
        },
        "messages": {
            "total": total_messages,
            "tokens_used": total_prompt_tokens + total_completion_tokens,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens
        },
        "feedbacks": {
            "pending": pending_feedbacks
        }
    }


@router.get("/users/trend")
async def get_users_trend(
    period: str = Query("30d", pattern="^(7d|30d|90d)$"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user)
):
    """获取用户注册趋势"""
    logger.info("get_users_trend_request", period=period)

    days = int(period.replace("d", ""))
    start_date = datetime.now().date() - timedelta(days=days)

    results = db.query(
        func.date(User.created_at).label("date"),
        func.count(User.id).label("count")
    ).filter(
        func.date(User.created_at) >= start_date
    ).group_by(
        func.date(User.created_at)
    ).order_by(
        func.date(User.created_at)
    ).all()

    data = [{"date": str(r.date), "count": r.count} for r in results]

    return {
        "period": period,
        "data": data
    }


@router.get("/users/source")
async def get_users_source(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user)
):
    """获取用户来源分布"""
    logger.info("get_users_source_request")

    results = db.query(
        User.source,
        func.count(User.id).label("count")
    ).group_by(
        User.source
    ).all()

    data = []
    for r in results:
        source = r.source or "unknown"
        # 标准化来源名称
        if source == "miniapp":
            source_label = "小程序"
        elif source == "web":
            source_label = "网页"
        else:
            source_label = source
        data.append({
            "source": source,
            "label": source_label,
            "count": r.count
        })

    return {"data": data}


@router.get("/conversations/trend")
async def get_conversations_trend(
    period: str = Query("7d", pattern="^(7d|30d|90d)$"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user)
):
    """获取对话趋势"""
    logger.info("get_conversations_trend_request", period=period)

    days = int(period.replace("d", ""))
    start_date = datetime.now().date() - timedelta(days=days)

    results = db.query(
        func.date(Conversation.created_at).label("date"),
        func.count(Conversation.id).label("count")
    ).filter(
        func.date(Conversation.created_at) >= start_date
    ).group_by(
        func.date(Conversation.created_at)
    ).order_by(
        func.date(Conversation.created_at)
    ).all()

    data = [{"date": str(r.date), "count": r.count} for r in results]

    return {
        "period": period,
        "data": data
    }


# ==================== 用户配额管理 ====================

class SetQuotaRequest(BaseModel):
    """设置用户配额请求"""
    total_quota: int = Field(..., description="总配额，-1 表示无限制")
    period: str = Field("never", description="重置周期: daily, monthly, never")
    source: str = Field("admin_grant", description="来源: free, paid, admin_grant")


class QuotaInfo(BaseModel):
    """配额信息"""
    type: str
    total: int
    used: int
    remaining: int
    is_unlimited: bool
    period: str
    source: str


class UserStatsDetail(BaseModel):
    """用户详细统计"""
    user_id: int
    email: Optional[str]
    nickname: Optional[str]
    quotas: List[QuotaInfo]
    usage: dict
    conversations_count: int
    messages_count: int
    created_at: datetime
    last_login_at: Optional[datetime]


class UserRankingItem(BaseModel):
    """用户排行榜项"""
    user_id: int
    email: Optional[str]
    nickname: Optional[str]
    value: int  # 排序值（对话数/消息数/token数等）


@router.get("/users/{user_id}/stats")
async def get_user_stats(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user)
):
    """获取指定用户的详细统计"""
    logger.info("get_user_stats_request", user_id=user_id)

    # 查询用户
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # 获取配额和使用统计
    stats = QuotaService.get_user_stats(db, user_id)

    # 对话数
    conversations_count = db.query(func.count(Conversation.id)).filter(
        Conversation.user_id == user_id
    ).scalar() or 0

    # 消息数
    messages_count = db.query(func.count(Message.id)).filter(
        Message.user_id == user_id
    ).scalar() or 0

    return {
        "user_id": user_id,
        "email": user.email,
        "nickname": user.nickname,
        "quotas": stats["quotas"],
        "usage": stats["usage"],
        "conversations_count": conversations_count,
        "messages_count": messages_count,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


@router.post("/users/{user_id}/quota")
async def set_user_quota(
    user_id: int,
    req: SetQuotaRequest,
    quota_type: str = Query("chat", description="配额类型"),
    db: Session = Depends(get_db_tx),
    _admin: User = Depends(get_admin_user)
):
    """设置用户配额"""
    logger.info("set_user_quota_request", user_id=user_id, quota_type=quota_type, req=req.model_dump())

    # 检查用户是否存在
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # 设置配额
    quota = QuotaService.set_user_quota(
        db=db,
        user_id=user_id,
        quota_type=quota_type,
        total_quota=req.total_quota,
        period=req.period,
        source=req.source,
    )

    return {
        "success": True,
        "quota": {
            "type": quota.quota_type,
            "total": quota.total_quota,
            "used": quota.used_quota,
            "remaining": quota.remaining,
            "is_unlimited": quota.is_unlimited,
            "period": quota.period,
            "source": quota.source,
        }
    }


@router.get("/users/ranking")
async def get_users_ranking(
    order_by: str = Query("conversations", pattern="^(conversations|messages|tokens)$"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user)
):
    """获取用户使用排行榜"""
    logger.info("get_users_ranking_request", order_by=order_by, limit=limit)

    if order_by == "conversations":
        # 按对话数排序
        results = db.query(
            User.id,
            User.email,
            User.nickname,
            func.count(Conversation.id).label("value")
        ).outerjoin(
            Conversation, User.id == Conversation.user_id
        ).group_by(
            User.id
        ).order_by(
            desc("value")
        ).limit(limit).all()

    elif order_by == "messages":
        # 按消息数排序
        results = db.query(
            User.id,
            User.email,
            User.nickname,
            func.count(Message.id).label("value")
        ).outerjoin(
            Message, User.id == Message.user_id
        ).group_by(
            User.id
        ).order_by(
            desc("value")
        ).limit(limit).all()

    else:  # tokens
        # 按 token 消耗排序
        results = db.query(
            User.id,
            User.email,
            User.nickname,
            (func.coalesce(func.sum(Message.prompt_tokens), 0) +
             func.coalesce(func.sum(Message.completion_tokens), 0)).label("value")
        ).outerjoin(
            Message, User.id == Message.user_id
        ).group_by(
            User.id
        ).order_by(
            desc("value")
        ).limit(limit).all()

    data = [
        {
            "user_id": r.id,
            "email": r.email,
            "nickname": r.nickname,
            "value": r.value or 0,
        }
        for r in results
    ]

    return {
        "order_by": order_by,
        "limit": limit,
        "data": data
    }
