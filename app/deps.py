# app/deps.py
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.orm import Session

from app.security import decode_token
from app.db import get_db
from app import models
from app.config import settings


# 让 Swagger “Authorize” 按钮可用；虽不必真的走 /auth/login 表单流，但可复用取 token 的机制
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def _extract_bearer_token(request: Request) -> Optional[str]:
    """
    尝试从 Authorization 头中提取 Bearer Token。
    返回 None 表示未提供或格式不正确（而不是抛异常，便于“可选用户”依赖）。
    """
    auth: str = request.headers.get("Authorization")
    if not auth:
        return None
    scheme, param = get_authorization_scheme_param(auth)
    if not scheme or scheme.lower() != "bearer":
        return None
    return param or None


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token_from_swagger: Optional[str] = Depends(oauth2_scheme),
) -> models.User:
    """
    强制需要登录的依赖：
    - 优先从 Swagger 的 oauth2_scheme 取 token（便于交互式调试）
    - 若没有，再从原始 Authorization 头里取
    - 成功解析后用 payload['sub'] 查询用户
    """
    token = token_from_swagger or _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if not sub:
            raise ValueError("Invalid token payload: missing 'sub'")
        user_id = int(sub)
    except Exception:
        # 统一返回 401，避免泄露细节
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user: Optional[models.User] = db.query(models.User).get(user_id)  # type: ignore[arg-type]
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


async def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
    token_from_swagger: Optional[str] = Depends(oauth2_scheme),
) -> Optional[models.User]:
    """
    可选登录的依赖：
    - 若带了合法 token，返回 User
    - 若未带或无效，返回 None（不抛异常）
    适合“读接口，但登录用户可享更多信息”的场景。
    """
    token = token_from_swagger or _extract_bearer_token(request)
    if not token:
        return None

    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if not sub:
            return None
        user_id = int(sub)
        user: Optional[models.User] = db.query(models.User).get(user_id)  # type: ignore[arg-type]
        return user
    except Exception:
        return None


async def get_admin_user(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    """
    仅管理员可用的依赖。
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privilege required")
    return current_user
