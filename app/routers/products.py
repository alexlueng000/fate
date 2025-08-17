from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db, engine
from .. import models
from ..schemas import ProductOut

router = APIRouter(prefix="/products", tags=["products"])

@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)):
    rows = db.query(models.Product).filter_by(active=True).all()
    return [ProductOut(id=r.id, sku=r.sku, name=r.name, type=r.type, price=r.price, currency=r.currency) for r in rows]
