# app/schemas/phone_auth.py
"""
Pydantic schemas for phone authentication
"""
from typing import Optional
from pydantic import BaseModel, Field


class PhoneSendCodeRequest(BaseModel):
    """Request schema for sending verification code"""
    phone: str = Field(..., min_length=11, max_length=11, description="手机号（11位）")
    purpose: str = Field(default="login", pattern="^(login|bind|verify)$", description="验证码用途")
    captcha_ticket: Optional[str] = Field(None, description="图形验证码票据")
    captcha_randstr: Optional[str] = Field(None, description="图形验证码随机串")


class PhoneSendCodeResponse(BaseModel):
    """Response schema for sending verification code"""
    success: bool = Field(..., description="是否发送成功")
    message: str = Field(..., description="提示信息")
    expires_in: int = Field(default=300, description="验证码有效期（秒）")
    rate_limit_reset: int = Field(default=60, description="下次可发送时间（秒）")


class PhoneLoginRequest(BaseModel):
    """Request schema for phone login"""
    phone: str = Field(..., min_length=11, max_length=11, description="手机号（11位）")
    code: str = Field(..., min_length=6, max_length=6, description="验证码（6位）")
    nickname: Optional[str] = Field(None, max_length=64, description="昵称（仅首次注册时使用）")
    avatar_url: Optional[str] = Field(None, max_length=256, description="头像URL")


class PhoneLoginResponse(BaseModel):
    """Response schema for phone login"""
    access_token: str = Field(..., description="JWT访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    user: dict = Field(..., description="用户信息")
    is_new_user: bool = Field(..., description="是否为新注册用户")
