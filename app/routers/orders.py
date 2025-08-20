from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
# from ..security import get_current_user
from .. import models
from ..schemas import CreateOrderRequest, OrderOut, PrepayRequest, PrepayResponse
from ..services.payments import create_prepay_stub

router = APIRouter(prefix="/orders", tags=["orders"])

@router.post("/create", response_model=OrderOut)
def create_order(req: CreateOrderRequest, db: Session = Depends(get_db)):
    prod = db.query(models.Product).filter_by(sku=req.sku, active=True).first()
    if not prod:
        raise HTTPException(404, "product not found")
    order = models.Order(user_id=user.id, product_id=prod.id, amount=prod.price, status="pending")
    db.add(order); db.commit(); db.refresh(order)
    return OrderOut(order_id=order.id, amount=order.amount, status=order.status)

@router.post("/prepay", response_model=PrepayResponse)
def prepay(req: PrepayRequest, db: Session = Depends(get_db)):
    order = db.get(models.Order, req.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    if order.status != "pending":
        raise HTTPException(400, "order not pending")
    prepay_id, pay_params = create_prepay_stub(db, order, openid=req.openid)
    return PrepayResponse(prepay_id=prepay_id, pay_params=pay_params)
