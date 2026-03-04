# app/routers/message_rating.py
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db_tx
from ..deps import get_current_user_optional
from ..models import User, MessageRating, Message
from ..schemas.message_rating import (
    MessageRatingCreate,
    MessageRatingResp,
    UserRatingResp,
    MessageRatingOkResp,
)
from app.core.logging import get_logger

logger = get_logger("message_rating")
router = APIRouter(prefix="/chat/messages", tags=["message_rating"])


@router.post("/{message_id}/rating", response_model=MessageRatingOkResp)
def submit_rating(
    message_id: int,
    req: MessageRatingCreate,
    db: Session = Depends(get_db_tx),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    提交对AI消息的评价（点赞/点踩）

    - 点踩时可选择原因
    - 点踩时会保存命盘数据用于后续分析
    - 每个用户对每条消息只能评价一次，重复提交会更新原评价
    """
    # 验证消息存在
    message = db.get(Message, message_id)
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在")

    user_id = current_user.id if current_user else None

    # 处理理由：如果选择"其他"且提供了自定义理由，使用自定义理由
    final_reason = req.reason
    if req.reason == "other" and req.custom_reason:
        # 验证自定义理由长度
        custom_text = req.custom_reason.strip()
        if len(custom_text) < 15:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="自定义理由至少需要15个字"
            )
        # 截断到500字符并保存
        final_reason = custom_text[:500]

    # 检查是否已有评价
    existing_rating = (
        db.query(MessageRating)
        .filter(MessageRating.message_id == message_id)
        .filter(MessageRating.user_id == user_id)
        .first()
    )

    if existing_rating:
        # 更新已有评价
        existing_rating.rating_type = req.rating_type
        existing_rating.reason = final_reason
        existing_rating.paipan_data = req.paipan_data
        logger.info(
            "rating_updated",
            message_id=message_id,
            user_id=user_id,
            rating_type=req.rating_type,
            reason=final_reason,
            is_custom=req.reason == "other",
        )
    else:
        # 创建新评价
        new_rating = MessageRating(
            message_id=message_id,
            user_id=user_id,
            rating_type=req.rating_type,
            reason=final_reason,
            paipan_data=req.paipan_data,
        )
        db.add(new_rating)
        logger.info(
            "rating_created",
            message_id=message_id,
            user_id=user_id,
            rating_type=req.rating_type,
            reason=final_reason,
            is_custom=req.reason == "other",
        )

    db.commit()
    return MessageRatingOkResp(ok=True)


@router.get("/{message_id}/rating", response_model=UserRatingResp)
def get_rating(
    message_id: int,
    db: Session = Depends(get_db_tx),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    获取当前用户对指定消息的评价状态

    返回当前用户是否已对该消息进行评价，以及评价详情
    """
    # 验证消息存在
    message = db.get(Message, message_id)
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在")

    user_id = current_user.id if current_user else None

    # 查询用户评价
    rating = (
        db.query(MessageRating)
        .filter(MessageRating.message_id == message_id)
        .filter(MessageRating.user_id == user_id)
        .first()
    )

    rating_resp = None
    if rating:
        rating_resp = MessageRatingResp(
            id=rating.id,
            rating_type=rating.rating_type,
            reason=rating.reason,
            created_at=rating.created_at,
        )

    return UserRatingResp(message_id=message_id, user_rating=rating_resp)
