"""
密码重置服务
- 验证码生成、存储、验证
- 频率限制
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import select, func, and_, update
from sqlalchemy.orm import Session

from app.models.password_reset import PasswordResetCode
from app.models.user import User
from app.services.users import get_by_email, set_password_hash
from app.security import hash_password


# 配置常量
CODE_LENGTH = 6
CODE_EXPIRE_MINUTES = 15
RATE_LIMIT_SECONDS = 60
DAILY_LIMIT = 5
MAX_FAILED_ATTEMPTS = 5


def generate_code() -> str:
    """生成6位数字验证码"""
    return ''.join(random.choices(string.digits, k=CODE_LENGTH))


def can_send_code(db: Session, email: str) -> Tuple[bool, Optional[str]]:
    """
    检查是否可以发送验证码

    Returns:
        (can_send, error_message)
    """
    email = email.strip().lower()
    now = datetime.now(timezone.utc)

    # 检查频率限制：60秒内不能重复发送
    recent = db.execute(
        select(PasswordResetCode)
        .where(
            and_(
                PasswordResetCode.email == email,
                PasswordResetCode.created_at > now - timedelta(seconds=RATE_LIMIT_SECONDS)
            )
        )
        .order_by(PasswordResetCode.created_at.desc())
        .limit(1)
    ).scalars().first()

    if recent:
        # 计算剩余等待时间
        created_at = recent.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        wait_seconds = RATE_LIMIT_SECONDS - int((now - created_at).total_seconds())
        if wait_seconds > 0:
            return False, f"请求过于频繁，请 {wait_seconds} 秒后重试"

    # 检查每日限制
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily_count = db.execute(
        select(func.count(PasswordResetCode.id))
        .where(
            and_(
                PasswordResetCode.email == email,
                PasswordResetCode.created_at >= today_start
            )
        )
    ).scalar() or 0

    if daily_count >= DAILY_LIMIT:
        return False, f"今日请求次数已达上限（{DAILY_LIMIT}次），请明天再试"

    return True, None


def create_reset_code(
    db: Session,
    email: str,
    ip_address: Optional[str] = None,
) -> PasswordResetCode:
    """
    创建密码重置验证码

    - 会使之前未使用的验证码失效（通过设置过期时间）
    """
    email = email.strip().lower()
    now = datetime.now(timezone.utc)

    # 使之前的验证码失效
    db.execute(
        update(PasswordResetCode)
        .where(
            and_(
                PasswordResetCode.email == email,
                PasswordResetCode.is_used == False,
                PasswordResetCode.expires_at > now
            )
        )
        .values(expires_at=now)
    )

    # 创建新验证码
    code = PasswordResetCode(
        email=email,
        code=generate_code(),
        expires_at=now + timedelta(minutes=CODE_EXPIRE_MINUTES),
        ip_address=ip_address,
    )
    db.add(code)
    db.flush()

    return code


def verify_and_reset_password(
    db: Session,
    email: str,
    code: str,
    new_password: str,
) -> Tuple[bool, str]:
    """
    验证验证码并重置密码

    Returns:
        (success, message)
    """
    email = email.strip().lower()
    now = datetime.now(timezone.utc)

    # 查找用户
    user = get_by_email(db, email)
    if not user:
        return False, "邮箱不存在"

    # 查找有效的验证码
    reset_code = db.execute(
        select(PasswordResetCode)
        .where(
            and_(
                PasswordResetCode.email == email,
                PasswordResetCode.is_used == False,
                PasswordResetCode.expires_at > now
            )
        )
        .order_by(PasswordResetCode.created_at.desc())
        .limit(1)
    ).scalars().first()

    if not reset_code:
        return False, "验证码已过期或不存在，请重新获取"

    # 检查失败次数
    if reset_code.failed_attempts >= MAX_FAILED_ATTEMPTS:
        return False, "验证码已失效，请重新获取"

    # 验证验证码
    if reset_code.code != code:
        reset_code.failed_attempts += 1
        db.flush()
        remaining = MAX_FAILED_ATTEMPTS - reset_code.failed_attempts
        if remaining > 0:
            return False, f"验证码错误，还剩 {remaining} 次尝试机会"
        else:
            return False, "验证码已失效，请重新获取"

    # 验证成功，重置密码
    try:
        password_hash = hash_password(new_password)
        set_password_hash(db, user, password_hash)

        # 标记验证码为已使用
        reset_code.is_used = True
        db.flush()

        return True, "密码重置成功"

    except ValueError as e:
        return False, str(e)
