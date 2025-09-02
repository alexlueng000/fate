# app/services/products.py
from __future__ import annotations

from typing import Optional, List

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

# from app.models import Product


def list_products(
    db: Session,
    *,
    active_only: bool = True,
    limit: Optional[int] = None,
    offset: int = 0,
    order_by: str = "id",
    desc: bool = False,
    search: Optional[str] = None,
) -> List[Product]:
    """
    列出商品（只读）。
    - active_only=True 仅返回在售商品
    - 支持简单搜索（code/name LIKE）
    - 支持分页与排序（白名单列）
    """
    stmt = select(Product)

    if active_only:
        stmt = stmt.where(Product.active.is_(True))

    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(Product.code.like(like), Product.name.like(like))
        )

    # 排序白名单，避免任意列名注入
    order_map = {
        "id": Product.id,
        "code": Product.code,
        "name": Product.name,
        "price_cents": Product.price_cents,
        "currency": Product.currency,
        "active": Product.active,
    }
    col = order_map.get(order_by, Product.id)
    stmt = stmt.order_by(col.desc() if desc else col.asc())

    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    return list(db.execute(stmt).scalars().all())


def get_by_code(
    db: Session,
    code: str,
    *,
    active_only: Optional[bool] = None,
) -> Optional[Product]:
    """
    按商品编码获取商品；active_only:
      - True  仅在售
      - False 包含已下架
      - None  忽略上下架（同 False）
    """
    stmt = select(Product).where(Product.code == code)
    if active_only is True:
        stmt = stmt.where(Product.active.is_(True))
    return db.execute(stmt).scalars().first()


def get_by_id(
    db: Session,
    product_id: int,
    *,
    active_only: Optional[bool] = None,
) -> Optional[Product]:
    """
    按 ID 获取商品；active_only 语义同上。
    """
    stmt = select(Product).where(Product.id == product_id)
    if active_only is True:
        stmt = stmt.where(Product.active.is_(True))
    return db.execute(stmt).scalars().first()
