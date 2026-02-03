# app/routers/admin_stats.py
"""
管理后台统计分析 API

提供以下统计数据：
- 总览统计（用户数、对话数、消息数、反馈数）
- 用户注册趋势
- 用户来源分布
- 对话趋势
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_admin_user
from app.models import User
from app.models.chat import Conversation, Message
from app.models.feedback import Feedback
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
    period: str = Query("30d", regex="^(7d|30d|90d)$"),
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
    period: str = Query("7d", regex="^(7d|30d|90d)$"),
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
