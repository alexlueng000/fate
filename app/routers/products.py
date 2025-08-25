# app/routers/products.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import ProductOut
from app.services.products import get_by_code
from app.config import settings

router = APIRouter(prefix="/products", tags=["products"])

# 默认售卖的唯一商品（可在 settings.single_product_code 覆盖，默认用我们之前种子的 REPORT_UNLOCK）
SINGLE_PRODUCT_CODE: str = getattr(settings, "single_product_code", "REPORT_UNLOCK")


@router.get("/default", response_model=ProductOut)
def get_default_product(db: Session = Depends(get_db)) -> ProductOut:
    """
    获取当前唯一售卖的商品（默认商品）。
    """
    prod = get_by_code(db, SINGLE_PRODUCT_CODE, active_only=True)
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not available",
        )
    return prod


@router.get("/{code}", response_model=ProductOut)
def get_product_by_code(code: str, db: Session = Depends(get_db)) -> ProductOut:
    """
    按商品编码获取商品（保留扩展点；现在只有默认单品）。
    """
    prod = get_by_code(db, code, active_only=True)
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    return prod
