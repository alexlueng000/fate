from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_admin_user
from app.schemas import ProductDetailOut
from app.services.products import get_by_id, list_products


router = APIRouter(
    prefix="/admin/products",
    tags=["admin-products"],
    dependencies=[Depends(get_admin_user)],
)


class ProductPriceUpdate(BaseModel):
    price_cents: int = Field(..., ge=1, le=100_000_000, description="商品价格，单位：分")


@router.get("", response_model=list[ProductDetailOut])
def get_admin_products(db: Session = Depends(get_db)) -> list[ProductDetailOut]:
    """返回全部商品，包含已下架商品，供后台维护价格。"""
    return list_products(db, active_only=False)


@router.patch("/{product_id}/price", response_model=ProductDetailOut)
def update_product_price(
    product_id: int,
    payload: ProductPriceUpdate,
    db: Session = Depends(get_db),
) -> ProductDetailOut:
    """更新后续新订单使用的商品价格；历史订单金额不会被改动。"""
    product = get_by_id(db, product_id, active_only=None)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")

    product.price_cents = payload.price_cents
    db.commit()
    db.refresh(product)
    return product
