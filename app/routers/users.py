# app/routers/users.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db_tx
from app.schemas import LoginRequest, Token, UserOut
from app.security import create_access_token
from app.services.users import get_or_create_by_openid
from app.deps import get_current_user
from app.models import User
from app.config import settings

router = APIRouter(tags=["auth", "users"])

# 开发态：固定一个可复用的 dev openid，避免每次都新建用户
DEV_OPENID = getattr(settings, "dev_openid", "dev_openid")


@router.post("/auth/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db_tx)) -> Token:
    """
    登录（开发态）：
    - 传 openid：直登/创建
    - 传 js_code=dev：使用固定 DEV_OPENID 直登/创建
    - 其他 js_code：当前未实现微信换取 openid，返回 400
    """
    if payload.openid:
        openid = payload.openid
    elif payload.js_code:
        if payload.js_code == "dev":
            openid = DEV_OPENID
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WeChat login not configured; use js_code=dev or provide openid",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide openid or js_code",
        )

    user = get_or_create_by_openid(db, openid, nickname=payload.nickname)
    token = create_access_token(user.id, extra={"is_admin": user.is_admin})
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """返回当前登录用户信息。"""
    return current_user
