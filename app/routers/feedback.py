# app/routers/feedback.py
"""用户反馈相关接口"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db import get_db
from app.deps import get_current_user, get_admin_user, get_current_user_optional
from app.models.user import User
from app.models.feedback import Feedback


router = APIRouter(tags=["feedback"])


# ================================== 请求/响应模型 ==================================

class FeedbackCreate(BaseModel):
    """提交反馈请求"""
    type: str = Field(default="other", description="反馈类型: bug/feature/question/other")
    content: str = Field(..., min_length=10, max_length=2000, description="反馈内容")
    contact: Optional[str] = Field(None, max_length=100, description="联系方式")


class FeedbackOut(BaseModel):
    """反馈响应"""
    id: int
    type: str
    content: str
    contact: Optional[str]
    status: str
    admin_reply: Optional[str]
    replied_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FeedbackAdminOut(FeedbackOut):
    """管理员查看的反馈响应（包含用户信息）"""
    user_id: Optional[int]
    user_email: Optional[str] = None
    user_username: Optional[str] = None
    replied_by: Optional[int]
    replied_by_username: Optional[str] = None


class FeedbackReply(BaseModel):
    """回复反馈请求"""
    reply: str = Field(..., min_length=1, max_length=2000, description="回复内容")


class FeedbackStatusUpdate(BaseModel):
    """更新反馈状态请求"""
    status: str = Field(..., description="状态: pending/processing/resolved/closed")


class FeedbackListResponse(BaseModel):
    """反馈列表响应"""
    items: List[FeedbackAdminOut]
    total: int
    page: int
    page_size: int


# ================================== 用户接口 ==================================

@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> Feedback:
    """
    提交反馈（可匿名）
    - 登录用户自动关联 user_id
    - 未登录用户可匿名提交
    """
    # 验证反馈类型
    valid_types = ["bug", "feature", "question", "other"]
    if payload.type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的反馈类型，可选值: {', '.join(valid_types)}"
        )

    feedback = Feedback(
        user_id=current_user.id if current_user else None,
        type=payload.type,
        content=payload.content,
        contact=payload.contact or (current_user.email if current_user else None),
        status="pending",
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


@router.get("/feedback/my", response_model=List[FeedbackOut])
def get_my_feedbacks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Feedback]:
    """获取我的反馈列表"""
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")

    feedbacks = (
        db.query(Feedback)
        .filter(Feedback.user_id == current_user.id)
        .order_by(desc(Feedback.created_at))
        .all()
    )
    return feedbacks


# ================================== 管理员接口 ==================================

@router.get("/admin/feedbacks", response_model=FeedbackListResponse)
def list_feedbacks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    status_filter: Optional[str] = Query(None, alias="status", description="状态筛选"),
    type_filter: Optional[str] = Query(None, alias="type", description="类型筛选"),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> dict:
    """管理员获取反馈列表（分页）"""
    query = db.query(Feedback)

    # 筛选条件
    if status_filter:
        query = query.filter(Feedback.status == status_filter)
    if type_filter:
        query = query.filter(Feedback.type == type_filter)

    # 总数
    total = query.count()

    # 分页
    feedbacks = (
        query
        .order_by(desc(Feedback.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 构建响应（包含用户信息）
    items = []
    for fb in feedbacks:
        item = FeedbackAdminOut(
            id=fb.id,
            type=fb.type,
            content=fb.content,
            contact=fb.contact,
            status=fb.status,
            admin_reply=fb.admin_reply,
            replied_at=fb.replied_at,
            created_at=fb.created_at,
            updated_at=fb.updated_at,
            user_id=fb.user_id,
            user_email=fb.user.email if fb.user else None,
            user_username=fb.user.username if fb.user else None,
            replied_by=fb.replied_by,
            replied_by_username=fb.admin.username if fb.admin else None,
        )
        items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/admin/feedbacks/{feedback_id}", response_model=FeedbackAdminOut)
def get_feedback_detail(
    feedback_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> FeedbackAdminOut:
    """管理员获取反馈详情"""
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈不存在")

    return FeedbackAdminOut(
        id=fb.id,
        type=fb.type,
        content=fb.content,
        contact=fb.contact,
        status=fb.status,
        admin_reply=fb.admin_reply,
        replied_at=fb.replied_at,
        created_at=fb.created_at,
        updated_at=fb.updated_at,
        user_id=fb.user_id,
        user_email=fb.user.email if fb.user else None,
        user_username=fb.user.username if fb.user else None,
        replied_by=fb.replied_by,
        replied_by_username=fb.admin.username if fb.admin else None,
    )


@router.post("/admin/feedbacks/{feedback_id}/reply", response_model=FeedbackAdminOut)
def reply_feedback(
    feedback_id: int,
    payload: FeedbackReply,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> FeedbackAdminOut:
    """管理员回复反馈"""
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈不存在")

    fb.admin_reply = payload.reply
    fb.replied_at = datetime.now()
    fb.replied_by = admin.id
    if fb.status == "pending":
        fb.status = "processing"

    db.commit()
    db.refresh(fb)

    return FeedbackAdminOut(
        id=fb.id,
        type=fb.type,
        content=fb.content,
        contact=fb.contact,
        status=fb.status,
        admin_reply=fb.admin_reply,
        replied_at=fb.replied_at,
        created_at=fb.created_at,
        updated_at=fb.updated_at,
        user_id=fb.user_id,
        user_email=fb.user.email if fb.user else None,
        user_username=fb.user.username if fb.user else None,
        replied_by=fb.replied_by,
        replied_by_username=fb.admin.username if fb.admin else None,
    )


@router.put("/admin/feedbacks/{feedback_id}/status", response_model=FeedbackAdminOut)
def update_feedback_status(
    feedback_id: int,
    payload: FeedbackStatusUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> FeedbackAdminOut:
    """管理员更新反馈状态"""
    valid_statuses = ["pending", "processing", "resolved", "closed"]
    if payload.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的状态，可选值: {', '.join(valid_statuses)}"
        )

    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈不存在")

    fb.status = payload.status
    db.commit()
    db.refresh(fb)

    return FeedbackAdminOut(
        id=fb.id,
        type=fb.type,
        content=fb.content,
        contact=fb.contact,
        status=fb.status,
        admin_reply=fb.admin_reply,
        replied_at=fb.replied_at,
        created_at=fb.created_at,
        updated_at=fb.updated_at,
        user_id=fb.user_id,
        user_email=fb.user.email if fb.user else None,
        user_username=fb.user.username if fb.user else None,
        replied_by=fb.replied_by,
        replied_by_username=fb.admin.username if fb.admin else None,
    )
