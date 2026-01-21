# app/routers/users.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db_tx
# from app.schemas import Token, UserOut  # 复用你现有的响应模型
from app.security import create_access_token, hash_password, verify_password
from app.services.users import (
    get_or_create_by_openid,
    create_user_email_password,
    get_by_email,
    touch_last_login,
)
from app.services.wechat import jscode2session
from app.deps import get_current_user
from app.models.user import User
from app.config import settings

router = APIRouter(tags=["auth", "users"])

# 开发态：固定一个可复用的 dev openid，避免每次都新建用户
DEV_OPENID = getattr(settings, "dev_openid", "dev_openid")


# ======== Pydantic 入参模型（就近定义，便于落地；如你更偏好放 app.schemas 也可迁走） ========

from pydantic import BaseModel, ConfigDict, EmailStr, Field

class WebRegisterRequest(BaseModel):
    """Web 注册：邮箱 + 密码 + 昵称(可选) + 头像(可选)"""
    email: EmailStr = Field(..., description="邮箱（唯一）")
    username: str = Field(..., description="用户名（唯一）")
    password: str = Field(..., min_length=6, max_length=128, description="明文密码（后台会做哈希）")
    nickname: str | None = Field(None, max_length=64, description="昵称（可选）")
    avatar_url: str | None = Field(None, max_length=256, description="头像URL（可选）")

class WebLoginRequest(BaseModel):
    """Web 登录：邮箱 + 密码"""
    email: EmailStr = Field(..., description="注册邮箱")
    password: str = Field(..., min_length=6, max_length=128, description="明文密码")

class MpLoginRequest(BaseModel):
    """
    小程序登录：
    - 提供 openid：直登/创建（生产不建议前端直接拿 openid，这里为了兼容与调试）
    - 或提供 js_code：
        * js_code=dev → 使用 DEV_OPENID（开发态）
        * 其他 js_code：需后端对接 code2session（此处未实现，给出 400）
    """
    openid: str | None = Field(None, max_length=64, description="微信 openid（兼容直登/调试）")
    js_code: str | None = Field(None, description="wx.login 返回的 code（生产应走 code2session）")
    nickname: str | None = Field(None, max_length=64, description="昵称（可选）")
    avatar_url: str | None = Field(None, max_length=256, description="头像URL（可选）")

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # 支持 SQLAlchemy 对象

    id: int
    email: str | None = None
    username: str | None = None  # 改为可选，兼容历史数据
    nickname: str | None = None
    avatar_url: str | None = None
    is_admin: bool

# 登录，注册返回 
class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

# ================================== Web 账户：注册 / 登录 ==================================

@router.post("/auth/web/register", response_model=AuthResponse)
def web_register(payload: WebRegisterRequest, db: Session = Depends(get_db_tx)) -> AuthResponse:
    """
    Web 注册（邮箱+密码）：
    - 校验邮箱唯一；密码在路由层进行哈希（推荐 Argon2id/bcrypt），再写入数据库。
    - 成功后直接签发 Access Token（与现有 token 体系一致），并返回。
    """
    # 1) 查重
    existing = get_by_email(db, payload.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册")

    # 2) 生成密码哈希（由 app.security.hash_password 实现）
    pwd_hash = hash_password(payload.password)

    # 3) 创建用户（source=web）
    user = create_user_email_password(
        db,
        email=str(payload.email),
        username=str(payload.username),
        password_hash=pwd_hash,
        nickname=payload.nickname,
        avatar_url=payload.avatar_url,
        is_admin=False,
        source="web",
    )

    # 4) 登录痕迹（可选）
    touch_last_login(db, user)

    # 5) 签发 JWT（与你现有逻辑保持一致）
    token = create_access_token(user.id, extra={"is_admin": user.is_admin})

    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(user)
    )


@router.post("/auth/web/login", response_model=AuthResponse)
def web_login(payload: WebLoginRequest, db: Session = Depends(get_db_tx)) -> AuthResponse:
    """
    Web 登录（邮箱+密码）：
    - 验证邮箱存在与密码匹配；状态为 blocked/deleted 的用户拒绝登录。
    """
    user = get_by_email(db, payload.email)
    if not user or not user.password_hash:
        # 统一返回 401，避免暴露“邮箱是否存在”的信息
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")

    # 账户状态检查（若你启用了 status 字段）
    if getattr(user, "status", 1) != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户不可用")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")

    # 登录痕迹
    touch_last_login(db, user)

    token = create_access_token(user.id, extra={"is_admin": user.is_admin})
    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(user)
    )


# ================================== 小程序：登录（开发态兼容版） ==================================

@router.post("/auth/mp/login", response_model=AuthResponse)
async def mp_login(payload: MpLoginRequest, db: Session = Depends(get_db_tx)) -> AuthResponse:
    """
    小程序登录（兼容直登与开发态）：
    - 有 openid → 幂等获取/创建。
    - 有 js_code：
        * js_code=dev → 使用 DEV_OPENID 直登/创建（开发环境）
        * 其他 js_code → 调用微信 jscode2session API 换取 openid/unionid/session_key。
    - 成功后签发 Access Token。
    """
    # 1) 确定 openid
    if payload.openid:
        openid = payload.openid
    elif payload.js_code:
        if payload.js_code == "dev":
            openid = DEV_OPENID
        else:
            # 调用微信 code2session
            if not settings.wx_appid or not settings.wx_secret:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="WX_APPID 或 WX_SECRET 未配置，请检查 .env 文件",
                )
            data = await jscode2session(settings.wx_appid, settings.wx_secret, payload.js_code)

            # 微信错误处理
            if "errcode" in data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"微信 API 错误: {data.get('errmsg')} (errcode: {data.get('errcode')})",
                )

            openid = data.get("openid")
            if not openid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="微信 API 未返回 openid",
                )
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="需提供 openid 或 js_code")

    # 2) 幂等获取/创建用户（source=miniapp）
    user = get_or_create_by_openid(
        db,
        openid=openid,
        nickname=payload.nickname,
        avatar_url=payload.avatar_url,
        source="miniapp",
    )

    # 3) 登录痕迹
    touch_last_login(db, user)

    # 4) 签发 Token
    token = create_access_token(user.id, extra={"is_admin": user.is_admin})
    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(user)
    )


# ================================== 兼容旧接口（保留原 /auth/login） ==================================

@router.post("/auth/login", response_model=AuthResponse, deprecated=True)
def login_compat(payload: MpLoginRequest, db: Session = Depends(get_db_tx)) -> AuthResponse:
    """
    兼容旧接口：保留原 /auth/login 行为（openid 或 js_code=dev）。
    建议前端逐步迁移到：
      - Web：/auth/web/login
      - 小程序：/auth/mp/login
    """
    return mp_login(payload, db)  # 直接复用小程序逻辑


# ================================== 当前用户信息 ==================================

@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """返回当前登录用户信息。"""
    return current_user
