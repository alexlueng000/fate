# app/services/users.py
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User


def get_by_id(db: Session, user_id: int) -> Optional[User]:
    """按 ID 获取用户。"""
    return db.get(User, user_id)


def get_by_openid(db: Session, openid: str) -> Optional[User]:
    """按 openid 获取用户。"""
    stmt = select(User).where(User.openid == openid)
    return db.execute(stmt).scalars().first()


def get_or_create_by_openid(
    db: Session,
    openid: str,
    *,
    nickname: Optional[str] = None,
    is_admin: Optional[bool] = None,
) -> User:
    """
    幂等获取或创建用户：
    - 若存在：可选地更新 nickname / is_admin（仅当参数不为 None 时）
    - 若不存在：创建并返回新用户
    说明：不在此函数内 commit；调用方可用 get_db_tx() 自动提交或手动提交。
    """
    user = get_by_openid(db, openid)
    if user:
        changed = False
        if nickname is not None and nickname != user.nickname:
            user.nickname = nickname
            changed = True
        if is_admin is not None and is_admin != user.is_admin:
            user.is_admin = is_admin
            changed = True
        if changed:
            db.flush()  # 让更改在当前事务可见
        return user

    # 不存在则创建；处理并发下的唯一约束竞争
    user = User(openid=openid, nickname=nickname, is_admin=is_admin or False)
    db.add(user)
    try:
        db.flush()  # 分配 ID，暴露唯一约束
        return user
    except IntegrityError:
        db.rollback()  # 回滚本次插入
        # 可能是并发下已被其他事务创建，回读一次
        existing = get_by_openid(db, openid)
        if existing:
            return existing
        # 理论上不应到这里；再次抛出给上层处理
        raise


def update_profile(
    db: Session,
    user: User,
    *,
    nickname: Optional[str] = None,
    is_admin: Optional[bool] = None,
) -> User:
    """
    更新用户资料（只更新传入的字段）。
    不在此函数内 commit；调用方负责提交。
    """
    changed = False
    if nickname is not None and nickname != user.nickname:
        user.nickname = nickname
        changed = True
    if is_admin is not None and is_admin != user.is_admin:
        user.is_admin = is_admin
        changed = True
    if changed:
        db.flush()
    return user
