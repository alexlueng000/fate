# app/routers/invitation_codes.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from app.db import get_db, get_db_tx
from app.deps import get_admin_user
from app.models.user import User
from app.models.invitation_code import InvitationCode, InvitationCodeUsage
from app.services.invitation_codes import (
    create_invitation_code,
    list_invitation_codes,
    count_invitation_codes,
    get_by_code,
    get_by_id,
    disable_code,
    enable_code,
    delete_code,
    get_code_usages,
)

router = APIRouter(
    prefix="/admin/invitation-codes",
    tags=["admin", "invitation-codes"],
)


# ========== Pydantic Schemas ==========

class CreateInvitationCodeRequest(BaseModel):
    """创建邀请码请求"""
    code: Optional[str] = Field(None, max_length=32, description="自定义邀请码（留空自动生成）")
    code_type: str = Field("single_use", description="类型: single_use/multi_use/unlimited")
    max_uses: int = Field(1, ge=0, description="最大使用次数（0=无限）")
    expires_at: Optional[datetime] = Field(None, description="过期时间")
    note: Optional[str] = Field(None, max_length=255, description="备注")


class BatchCreateRequest(BaseModel):
    """批量创建邀请码请求"""
    count: int = Field(..., ge=1, le=100, description="生成数量（1-100）")
    code_type: str = Field("single_use", description="类型: single_use/multi_use/unlimited")
    max_uses: int = Field(1, ge=0, description="最大使用次数（0=无限）")
    expires_at: Optional[datetime] = Field(None, description="过期时间")
    note: Optional[str] = Field(None, max_length=255, description="备注")


class InvitationCodeOut(BaseModel):
    """邀请码输出"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    code_type: str
    max_uses: int
    used_count: int
    status: int
    expires_at: Optional[datetime]
    created_by: Optional[int]
    note: Optional[str]
    created_at: datetime
    updated_at: datetime


class UsageRecordOut(BaseModel):
    """使用记录输出"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    code_id: int
    user_id: int
    used_at: datetime
    ip_address: Optional[str]


class ListResponse(BaseModel):
    """列表响应"""
    items: List[InvitationCodeOut]
    total: int
    limit: int
    offset: int


# ========== Endpoints ==========

@router.get("", response_model=ListResponse)
def list_codes(
    status: Optional[int] = Query(None, description="按状态筛选: 1=有效, 0=禁用, 2=过期"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """列出所有邀请码"""
    codes = list_invitation_codes(db, status=status, limit=limit, offset=offset)
    total = count_invitation_codes(db, status=status)
    return ListResponse(
        items=[InvitationCodeOut.model_validate(c) for c in codes],
        total=total,
        limit=limit,
        offset=offset
    )


@router.post("", response_model=InvitationCodeOut)
def create_code(
    payload: CreateInvitationCodeRequest,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """创建单个邀请码"""
    # 检查自定义邀请码是否已存在
    if payload.code:
        existing = get_by_code(db, payload.code)
        if existing:
            raise HTTPException(status_code=409, detail="该邀请码已存在")

    inv_code = create_invitation_code(
        db,
        code=payload.code,
        code_type=payload.code_type,
        max_uses=payload.max_uses,
        expires_at=payload.expires_at,
        created_by=admin.id,
        note=payload.note,
    )
    return InvitationCodeOut.model_validate(inv_code)


@router.post("/batch", response_model=List[InvitationCodeOut])
def batch_create_codes(
    payload: BatchCreateRequest,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """批量创建邀请码"""
    codes = []
    for _ in range(payload.count):
        inv_code = create_invitation_code(
            db,
            code_type=payload.code_type,
            max_uses=payload.max_uses,
            expires_at=payload.expires_at,
            created_by=admin.id,
            note=payload.note,
        )
        codes.append(InvitationCodeOut.model_validate(inv_code))
    return codes


@router.get("/{code_id}", response_model=InvitationCodeOut)
def get_code(
    code_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """获取邀请码详情"""
    inv_code = get_by_id(db, code_id)
    if not inv_code:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    return InvitationCodeOut.model_validate(inv_code)


@router.get("/{code_id}/usages", response_model=List[UsageRecordOut])
def get_usages(
    code_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """获取邀请码使用记录"""
    inv_code = get_by_id(db, code_id)
    if not inv_code:
        raise HTTPException(status_code=404, detail="邀请码不存在")

    usages = get_code_usages(db, code_id, limit=limit, offset=offset)
    return [UsageRecordOut.model_validate(u) for u in usages]


@router.patch("/{code_id}/disable")
def disable_invitation_code(
    code_id: int,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """禁用邀请码"""
    inv_code = disable_code(db, code_id)
    if not inv_code:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    return {"ok": True, "message": "邀请码已禁用"}


@router.patch("/{code_id}/enable")
def enable_invitation_code(
    code_id: int,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """启用邀请码"""
    inv_code = enable_code(db, code_id)
    if not inv_code:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    return {"ok": True, "message": "邀请码已启用"}


@router.delete("/{code_id}")
def delete_invitation_code(
    code_id: int,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """删除邀请码（软删除）"""
    inv_code = delete_code(db, code_id)
    if not inv_code:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    return {"ok": True, "message": "邀请码已删除"}
