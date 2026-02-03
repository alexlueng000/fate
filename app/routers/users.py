# app/routers/users.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.db import get_db, get_db_tx
# from app.schemas import Token, UserOut  # 复用你现有的响应模型
from app.security import create_access_token, hash_password, verify_password
from app.services.users import (
    get_or_create_by_openid,
    create_user_email_password,
    get_by_email,
    touch_last_login,
)
from app.services.invitation_codes import validate_code, use_code
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
    """Web 注册：邮箱 + 密码 + 邀请码 + 昵称(可选) + 头像(可选)"""
    email: EmailStr = Field(..., description="邮箱（唯一）")
    username: str = Field(..., description="用户名（唯一）")
    password: str = Field(..., min_length=6, max_length=128, description="明文密码（后台会做哈希）")
    invitation_code: str = Field(..., min_length=4, max_length=32, description="邀请码")
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
def web_register(
    request: Request,
    payload: WebRegisterRequest,
    db: Session = Depends(get_db_tx)
) -> AuthResponse:
    """
    Web 注册（邮箱+密码+邀请码）：
    - 先验证邀请码是否有效
    - 校验邮箱唯一；密码在路由层进行哈希（推荐 Argon2id/bcrypt），再写入数据库。
    - 成功后直接签发 Access Token（与现有 token 体系一致），并返回。
    """
    # 1) 验证邀请码
    is_valid, error_msg, inv_code = validate_code(db, payload.invitation_code)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    # 2) 查重
    existing = get_by_email(db, payload.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册")

    # 3) 生成密码哈希（由 app.security.hash_password 实现）
    pwd_hash = hash_password(payload.password)

    # 4) 创建用户（source=web）
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

    # 5) 记录邀请码使用
    client_ip = request.client.host if request.client else None
    use_code(db, inv_code, user.id, ip_address=client_ip)

    # 6) 登录痕迹（可选）
    touch_last_login(db, user)

    # 7) 签发 JWT（与你现有逻辑保持一致）
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


# ================================== 邀请码验证 ==================================

class ValidateInvitationCodeRequest(BaseModel):
    """验证邀请码请求"""
    code: str = Field(..., min_length=4, max_length=32, description="邀请码")


class ValidateInvitationCodeResponse(BaseModel):
    """验证邀请码响应"""
    valid: bool
    message: str


@router.post("/auth/validate-invitation-code", response_model=ValidateInvitationCodeResponse)
def validate_invitation_code(
    payload: ValidateInvitationCodeRequest,
    db: Session = Depends(get_db)
) -> ValidateInvitationCodeResponse:
    """
    验证邀请码是否有效（不消耗使用次数）
    - 用于前端实时验证
    """
    is_valid, error_msg, _ = validate_code(db, payload.code)
    return ValidateInvitationCodeResponse(
        valid=is_valid,
        message=error_msg if not is_valid else "邀请码有效"
    )


# ================================== 密码重置 ==================================

import asyncio
from app.services.password_reset import (
    can_send_code,
    create_reset_code,
    verify_and_reset_password,
    CODE_EXPIRE_MINUTES,
)
from app.services.email import email_service


class SendResetCodeRequest(BaseModel):
    """发送密码重置验证码请求"""
    email: EmailStr = Field(..., description="注册邮箱")


class SendResetCodeResponse(BaseModel):
    """发送密码重置验证码响应"""
    success: bool
    message: str
    expires_in: int = Field(default=900, description="验证码有效期（秒）")


class ResetPasswordRequest(BaseModel):
    """重置密码请求"""
    email: EmailStr = Field(..., description="注册邮箱")
    code: str = Field(..., min_length=6, max_length=6, description="6位验证码")
    new_password: str = Field(..., min_length=6, max_length=128, description="新密码")


class ResetPasswordResponse(BaseModel):
    """重置密码响应"""
    success: bool
    message: str


@router.post("/auth/password-reset/send-code", response_model=SendResetCodeResponse)
async def send_reset_code(
    request: Request,
    payload: SendResetCodeRequest,
    db: Session = Depends(get_db_tx),
) -> SendResetCodeResponse:
    """
    发送密码重置验证码

    - 验证邮箱是否存在
    - 检查频率限制（60秒/次）
    - 检查每日限制（5次/天）
    - 发送6位数字验证码到邮箱
    """
    email = str(payload.email).strip().lower()
    client_ip = request.client.host if request.client else None

    # 检查频率限制
    can_send, error_msg = can_send_code(db, email)
    if not can_send:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_msg
        )

    # 检查邮箱是否存在（为安全起见，即使不存在也返回成功）
    user = get_by_email(db, email)
    if not user:
        # 不暴露邮箱是否存在的信息
        return SendResetCodeResponse(
            success=True,
            message="如果该邮箱已注册，验证码将发送到您的邮箱",
            expires_in=CODE_EXPIRE_MINUTES * 60
        )

    # 创建验证码
    reset_code = create_reset_code(db, email, ip_address=client_ip)

    # 异步发送邮件（不阻塞响应）
    asyncio.create_task(
        email_service.send_password_reset_code(email, reset_code.code, CODE_EXPIRE_MINUTES)
    )

    return SendResetCodeResponse(
        success=True,
        message="验证码已发送到您的邮箱，请查收",
        expires_in=CODE_EXPIRE_MINUTES * 60
    )


@router.post("/auth/password-reset/reset", response_model=ResetPasswordResponse)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db_tx),
) -> ResetPasswordResponse:
    """
    验证验证码并重置密码

    - 验证验证码是否正确且未过期
    - 验证失败次数限制（5次）
    - 重置用户密码
    """
    success, message = verify_and_reset_password(
        db,
        email=str(payload.email),
        code=payload.code,
        new_password=payload.new_password,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    return ResetPasswordResponse(success=True, message=message)
