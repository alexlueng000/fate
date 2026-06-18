from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.schemas import ProductDetailOut, ProductOut
from app.services.products import get_by_code, list_products

router = APIRouter(prefix="/products", tags=["products"])

SINGLE_PRODUCT_CODE: str = getattr(settings, "single_product_code", "REPORT_UNLOCK")


@router.get("", response_model=list[ProductDetailOut])
def get_products(db: Session = Depends(get_db)) -> list[ProductDetailOut]:
    return list_products(db, active_only=True)


@router.get("/default", response_model=ProductOut)
def get_default_product(db: Session = Depends(get_db)) -> ProductOut:
    prod = get_by_code(db, SINGLE_PRODUCT_CODE, active_only=True)
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not available",
        )
    return prod


@router.get("/{code}", response_model=ProductDetailOut)
def get_product_by_code(code: str, db: Session = Depends(get_db)) -> ProductDetailOut:
    prod = get_by_code(db, code, active_only=True)
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    return prod
