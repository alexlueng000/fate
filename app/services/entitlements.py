# app/services/entitlements.py
from __future__ import annotations

from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Entitlement, User


def grant(
    db: Session,
    *,
    user: User,
    product_code: str,
) -> Entitlement:
    """
    授予用户某个 product_code 的使用权益（幂等）。
    - 已存在则直接返回现有记录
    - 不在本函数内 commit；调用方统一提交
    """
    # 先查，命中直接返回
    ent = _get(db, user_id=user.id, product_code=product_code)
    if ent:
        return ent

    # 不存在则插入；并发下由唯一索引兜底
    ent = Entitlement(user_id=user.id, product_code=product_code)
    db.add(ent)
    try:
        db.flush()  # 触发唯一约束并分配 id
        return ent
    except IntegrityError:
        db.rollback()
        # 并发竞争导致的重复授予，回读一次即可
        existing = _get(db, user_id=user.id, product_code=product_code)
        if existing:
            return existing
        # 极少数情况下仍失败，抛给上层
        raise


def has(
    db: Session,
    *,
    user: User,
    product_code: str,
) -> bool:
    """检查用户是否已获得指定权益。"""
    return _get(db, user_id=user.id, product_code=product_code) is not None


def list_by_user(
    db: Session,
    *,
    user: User,
    limit: int = 100,
    offset: int = 0,
) -> List[Entitlement]:
    """列出用户的全部权益（默认最多 100 条）。"""
    stmt = (
        select(Entitlement)
        .where(Entitlement.user_id == user.id)
        .order_by(Entitlement.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


# -------------------------
# 内部工具
# -------------------------
def _get(db: Session, *, user_id: int, product_code: str) -> Optional[Entitlement]:
    stmt = select(Entitlement).where(
        Entitlement.user_id == user_id, Entitlement.product_code == product_code
    )
    return db.execute(stmt).scalars().first()
