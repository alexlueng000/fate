# app/routers/profile.py
"""
用户档案 API 路由
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user
from app.models import User
from app.schemas.profile import (
    ProfileCreateRequest,
    ProfileUpdateRequest,
    ProfileReportSaveRequest,
    ProfileResponse,
    ProfileBriefResponse,
)
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/me", response_model=Optional[ProfileResponse])
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的档案

    Returns:
        用户档案信息，如果没有档案则返回 null
    """
    profile = ProfileService.get_user_profile(db, current_user.id)
    if not profile:
        return None

    return ProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        gender=profile.gender,
        calendar_type=profile.calendar_type,
        birth_date=profile.birth_date,
        birth_time=profile.birth_time,
        birth_location=profile.birth_location,
        birth_longitude=profile.birth_longitude,
        birth_latitude=profile.birth_latitude,
        bazi_chart=profile.bazi_chart,
        ai_report=profile.ai_report,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        display_info=profile.display_info,
        birth_datetime_str=profile.birth_datetime_str,
    )


@router.get("/me/brief", response_model=Optional[ProfileBriefResponse])
def get_my_profile_brief(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户档案的简要信息（用于聊天页顶部显示）

    Returns:
        档案简要信息，如果没有档案则返回 null
    """
    profile = ProfileService.get_user_profile(db, current_user.id)
    if not profile:
        return None

    return ProfileBriefResponse(
        id=profile.id,
        gender=profile.gender,
        birth_date=profile.birth_date,
        birth_time=profile.birth_time,
        birth_location=profile.birth_location,
        display_info=profile.display_info,
    )


@router.post("/create", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
def create_profile(
    data: ProfileCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    创建用户档案并生成命盘

    Args:
        data: 档案数据（出生信息）

    Returns:
        创建的档案信息（包含计算好的命盘）

    Raises:
        400: 用户已有档案
        500: 命盘计算失败
    """
    try:
        profile = ProfileService.create_profile(db, current_user.id, data)

        return ProfileResponse(
            id=profile.id,
            user_id=profile.user_id,
            gender=profile.gender,
            calendar_type=profile.calendar_type,
            birth_date=profile.birth_date,
            birth_time=profile.birth_time,
            birth_location=profile.birth_location,
            birth_longitude=profile.birth_longitude,
            birth_latitude=profile.birth_latitude,
            bazi_chart=profile.bazi_chart,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            display_info=profile.display_info,
            birth_datetime_str=profile.birth_datetime_str,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建档案失败: {str(e)}"
        )


@router.put("/update", response_model=ProfileResponse)
def update_profile(
    data: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    更新用户档案并自动重新计算命盘

    Args:
        data: 更新数据（只更新提供的字段）

    Returns:
        更新后的档案信息（包含重新计算的命盘）

    Raises:
        404: 用户没有档案
        500: 更新失败
    """
    try:
        profile = ProfileService.update_profile(db, current_user.id, data)

        return ProfileResponse(
            id=profile.id,
            user_id=profile.user_id,
            gender=profile.gender,
            calendar_type=profile.calendar_type,
            birth_date=profile.birth_date,
            birth_time=profile.birth_time,
            birth_location=profile.birth_location,
            birth_longitude=profile.birth_longitude,
            birth_latitude=profile.birth_latitude,
            bazi_chart=profile.bazi_chart,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            display_info=profile.display_info,
            birth_datetime_str=profile.birth_datetime_str,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新档案失败: {str(e)}"
        )


@router.post("/report", response_model=dict)
def save_profile_report(
    data: ProfileReportSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存命理报告"""
    profile = ProfileService.get_user_profile(db, current_user.id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户没有档案"
        )
    profile.ai_report = data.ai_report
    db.commit()
    return {"ok": True}


@router.delete("/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除用户档案

    注意：删除档案后，关联的聊天会话的 profile_id 将被设置为 NULL

    Raises:
        404: 用户没有档案
    """
    success = ProfileService.delete_profile(db, current_user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户没有档案"
        )
    return None
