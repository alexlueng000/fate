from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Product
from app.services.membership_service import grant_product_entitlements


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
    stmt = select(Product)

    if active_only:
        stmt = stmt.where(Product.active.is_(True))

    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Product.code.like(like), Product.name.like(like)))

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
    stmt = select(Product).where(Product.id == product_id)
    if active_only is True:
        stmt = stmt.where(Product.active.is_(True))
    return db.execute(stmt).scalars().first()


def grant_product_quota(
    db: Session,
    *,
    user_id: int,
    product: Product,
    source: str = "purchase",
) -> Dict[str, int]:
    granted = grant_product_entitlements(db, user_id=user_id, product=product, source=source)
    label_map = {"chat": "bazi", "liuyao_chat": "liuyao"}
    return {label_map.get(key, key): value for key, value in granted.items()}
