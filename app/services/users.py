# app/services/users.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User


# ========== 工具函数 ==========

def _normalize_email(email: Optional[str]) -> Optional[str]:
    """
    统一邮箱大小写/空白处理。
    - None 或空字符串返回 None
    - 否则 strip + lower
    """
    if not email:
        return None
    e = email.strip().lower()
    return e or None


# ========== 基础查询 ==========

def get_by_id(db: Session, user_id: int) -> Optional[User]:
    """按主键 ID 获取用户。"""
    return db.get(User, user_id)


def get_by_openid(db: Session, openid: Optional[str]) -> Optional[User]:
    """
    按微信小程序 openid 获取用户。
    - 兼容 openid 为空：直接返回 None
    """
    if not openid:
        return None
    stmt = select(User).where(User.openid == openid)
    return db.execute(stmt).scalars().first()


def get_by_email(db: Session, email: Optional[str]) -> Optional[User]:
    """
    按邮箱获取用户（已做 normalize）。
    - None/空返回 None
    """
    e = _normalize_email(email)
    if not e:
        return None
    stmt = select(User).where(User.email == e)
    return db.execute(stmt).scalars().first()


def get_by_phone(db: Session, phone: Optional[str]) -> Optional[User]:
    """
    按手机号获取用户。
    - None/空返回 None
    - 这里不做格式化，调用方应确保入库格式一致
    """
    if not phone:
        return None
    stmt = select(User).where(User.phone == phone)
    return db.execute(stmt).scalars().first()


# ========== 幂等创建 / 更新（小程序 openid 场景） ==========

def get_or_create_by_openid(
    db: Session,
    openid: str,
    *,
    nickname: Optional[str] = None,
    avatar_url: Optional[str] = None,
    is_admin: Optional[bool] = None,
    source: Optional[str] = "miniapp",
) -> User:
    """
    幂等获取或创建（微信小程序）：
    - 若存在：仅更新传入且发生变化的字段（nickname / avatar_url / is_admin / source）。
    - 若不存在：创建并返回。
    - 不在此函数 commit；调用方负责提交或使用事务上下文。
    """
    if not openid:
        raise ValueError("openid 不能为空")

    user = get_by_openid(db, openid)
    if user:
        changed = False
        if nickname is not None and nickname != user.nickname:
            user.nickname = nickname
            changed = True
        if avatar_url is not None and avatar_url != user.avatar_url:
            user.avatar_url = avatar_url
            changed = True
        if is_admin is not None and is_admin != user.is_admin:
            user.is_admin = is_admin
            changed = True
        if source is not None and source != user.source:
            user.source = source
            changed = True
        if changed:
            db.flush()  # 让更改在当前事务可见
        return user

    # 不存在则创建；处理并发下唯一约束竞争
    user = User(
        openid=openid,
        nickname=nickname,
        avatar_url=avatar_url,
        is_admin=bool(is_admin) if is_admin is not None else False,
        source=source,
    )
    db.add(user)
    try:
        db.flush()  # 分配 ID，暴露唯一约束
        return user
    except IntegrityError:
        db.rollback()  # 回滚本次插入
        # 并发情况下可能已被其他事务创建，回读一次
        existing = get_by_openid(db, openid)
        if existing:
            return existing
        # 仍然找不到则抛出给上层处理
        raise


# ========== Web 邮箱/密码场景（最小可用） ==========

def create_user_email_password(
    db: Session,
    *,
    email: str,
    username: str,
    password_hash: str,
    nickname: Optional[str] = None,
    avatar_url: Optional[str] = None,
    is_admin: bool = False,
    source: str = "web",
) -> User:
    """
    用邮箱+密码创建用户（不在此函数 commit）。
    - email 必须唯一，内部会 normalize（lower/strip）。
    - password_hash 需由上层使用安全算法（建议 Argon2id）生成后传入。
    - 并发下若触发唯一约束，会回滚并回读后返回已存在用户。
    """
    e = _normalize_email(email)
    if not e:
        raise ValueError("email 不能为空")

    user = User(
        email=e,
        username=username,
        password_hash=password_hash,
        nickname=nickname,
        avatar_url=avatar_url,
        is_admin=is_admin,
        source=source,
    )
    db.add(user)
    try:
        db.flush()
        return user
    except IntegrityError:
        db.rollback()
        existing = get_by_email(db, e)
        if existing:
            return existing
        raise


def set_password_hash(db: Session, user: User, password_hash: str) -> User:
    """
    覆盖设置用户密码哈希（不在此函数 commit）。
    - 仅设置 hash，不处理明文；哈希由上层生成。
    """
    if not password_hash:
        raise ValueError("password_hash 不能为空")
    user.password_hash = password_hash
    db.flush()
    return user


# ========== 资料更新 / 登录痕迹 ==========

def update_profile(
    db: Session,
    user: User,
    *,
    nickname: Optional[str] = None,
    avatar_url: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    locale: Optional[str] = None,
    status: Optional[str] = None,
    is_admin: Optional[bool] = None,
) -> User:
    """
    更新用户资料（仅更新传入且变化的字段，不在此函数 commit）。
    - email 会 normalize；可能触发唯一约束，异常交由调用方处理（或外层捕获 IntegrityError）。
    """
    changed = False

    if nickname is not None and nickname != user.nickname:
        user.nickname = nickname
        changed = True

    if avatar_url is not None and avatar_url != user.avatar_url:
        user.avatar_url = avatar_url
        changed = True

    if email is not None:
        e = _normalize_email(email)
        if e != user.email:
            user.email = e
            changed = True

    if phone is not None and phone != user.phone:
        user.phone = phone
        changed = True

    if locale is not None and locale != user.locale:
        user.locale = locale
        changed = True

    if status is not None and status != user.status:
        user.status = status
        changed = True

    if is_admin is not None and is_admin != user.is_admin:
        user.is_admin = is_admin
        changed = True

    if changed:
        db.flush()
    return user


def touch_last_login(
    db: Session,
    user: User,
    *,
    ip: Optional[str] = None,
) -> User:
    """
    更新最近登录时间与IP（不在此函数 commit）。
    - 建议在登录成功/刷新令牌成功时调用。
    """
    user.last_login_at = datetime.now(timezone.utc)  # 模型列允许为 naive；与 DB func.now() 不冲突
    if ip:  
        user.last_login_ip = ip[:45]  # 兼容 IPv6 最大长度
    db.flush()
    return user
