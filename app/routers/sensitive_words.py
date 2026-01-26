# app/routers/sensitive_words.py
"""敏感词管理 API"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from app.db import get_db, get_db_tx
from app.deps import get_admin_user
from app.models.user import User
from app.services import sensitive_words as svc
from app.chat.content_filter import clear_cache


router = APIRouter(
    prefix="/admin/sensitive-words",
    tags=["admin", "sensitive-words"],
)


# ========== Pydantic Schemas ==========

class CreateWordRequest(BaseModel):
    """创建敏感词请求"""
    word: str = Field(..., min_length=1, max_length=64, description="敏感词")
    replacement: str = Field(..., min_length=1, max_length=128, description="替换词")
    category: str = Field("general", max_length=32, description="分类")
    is_regex: bool = Field(False, description="是否正则匹配")
    priority: int = Field(0, ge=0, description="优先级（越大越先匹配）")
    note: Optional[str] = Field(None, max_length=255, description="备注")


class UpdateWordRequest(BaseModel):
    """更新敏感词请求"""
    word: Optional[str] = Field(None, min_length=1, max_length=64)
    replacement: Optional[str] = Field(None, min_length=1, max_length=128)
    category: Optional[str] = Field(None, max_length=32)
    is_regex: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0)
    note: Optional[str] = Field(None, max_length=255)


class BatchCreateRequest(BaseModel):
    """批量创建敏感词请求"""
    words: List[CreateWordRequest] = Field(..., min_length=1, max_length=100)


class SensitiveWordOut(BaseModel):
    """敏感词输出"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    word: str
    replacement: str
    category: str
    is_regex: bool
    priority: int
    status: int
    note: Optional[str]
    created_at: datetime
    updated_at: datetime


class ListResponse(BaseModel):
    """列表响应"""
    items: List[SensitiveWordOut]
    total: int
    limit: int
    offset: int


# ========== Endpoints ==========

@router.get("", response_model=ListResponse)
def list_words(
    status: Optional[int] = Query(None, description="按状态筛选: 1=启用, 0=禁用"),
    category: Optional[str] = Query(None, description="按分类筛选"),
    search: Optional[str] = Query(None, description="搜索敏感词或替换词"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """列出所有敏感词"""
    words = svc.list_words(
        db, status=status, category=category, search=search,
        limit=limit, offset=offset
    )
    total = svc.count_words(db, status=status, category=category, search=search)
    return ListResponse(
        items=[SensitiveWordOut.model_validate(w) for w in words],
        total=total,
        limit=limit,
        offset=offset
    )


@router.post("", response_model=SensitiveWordOut)
def create_word(
    payload: CreateWordRequest,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """创建敏感词"""
    # 检查是否已存在
    existing = svc.get_by_word(db, payload.word)
    if existing:
        raise HTTPException(status_code=409, detail="该敏感词已存在")

    word = svc.create_word(
        db,
        word=payload.word,
        replacement=payload.replacement,
        category=payload.category,
        is_regex=payload.is_regex,
        priority=payload.priority,
        note=payload.note,
    )
    # 清除缓存
    clear_cache()
    return SensitiveWordOut.model_validate(word)


@router.post("/batch", response_model=List[SensitiveWordOut])
def batch_create_words(
    payload: BatchCreateRequest,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """批量创建敏感词"""
    words_data = [
        {
            "word": w.word,
            "replacement": w.replacement,
            "category": w.category,
            "is_regex": w.is_regex,
            "priority": w.priority,
            "note": w.note,
        }
        for w in payload.words
    ]
    created = svc.batch_create_words(db, words_data)
    # 清除缓存
    clear_cache()
    return [SensitiveWordOut.model_validate(w) for w in created]


@router.get("/{word_id}", response_model=SensitiveWordOut)
def get_word(
    word_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """获取敏感词详情"""
    word = svc.get_by_id(db, word_id)
    if not word:
        raise HTTPException(status_code=404, detail="敏感词不存在")
    return SensitiveWordOut.model_validate(word)


@router.put("/{word_id}", response_model=SensitiveWordOut)
def update_word(
    word_id: int,
    payload: UpdateWordRequest,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """更新敏感词"""
    # 检查新敏感词是否与其他记录冲突
    if payload.word:
        existing = svc.get_by_word(db, payload.word)
        if existing and existing.id != word_id:
            raise HTTPException(status_code=409, detail="该敏感词已存在")

    word = svc.update_word(
        db,
        word_id=word_id,
        word=payload.word,
        replacement=payload.replacement,
        category=payload.category,
        is_regex=payload.is_regex,
        priority=payload.priority,
        note=payload.note,
    )
    if not word:
        raise HTTPException(status_code=404, detail="敏感词不存在")
    # 清除缓存
    clear_cache()
    return SensitiveWordOut.model_validate(word)


@router.patch("/{word_id}/enable")
def enable_word(
    word_id: int,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """启用敏感词"""
    word = svc.enable_word(db, word_id)
    if not word:
        raise HTTPException(status_code=404, detail="敏感词不存在")
    # 清除缓存
    clear_cache()
    return {"ok": True, "message": "敏感词已启用"}


@router.patch("/{word_id}/disable")
def disable_word(
    word_id: int,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """禁用敏感词"""
    word = svc.disable_word(db, word_id)
    if not word:
        raise HTTPException(status_code=404, detail="敏感词不存在")
    # 清除缓存
    clear_cache()
    return {"ok": True, "message": "敏感词已禁用"}


@router.delete("/{word_id}")
def delete_word(
    word_id: int,
    db: Session = Depends(get_db_tx),
    admin: User = Depends(get_admin_user),
):
    """删除敏感词"""
    ok = svc.delete_word(db, word_id)
    if not ok:
        raise HTTPException(status_code=404, detail="敏感词不存在")
    # 清除缓存
    clear_cache()
    return {"ok": True, "message": "敏感词已删除"}


@router.post("/clear-cache")
def clear_word_cache(
    admin: User = Depends(get_admin_user),
):
    """清除敏感词缓存"""
    clear_cache()
    return {"ok": True, "message": "缓存已清除"}
