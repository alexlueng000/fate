import json
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models
from ..schemas import NotifyResult
from ..services.payments import mark_paid_and_grant
from ..config import settings

router = APIRouter(prefix="/pay/wechat", tags=["payments"])

@router.post("/notify", response_model=NotifyResult)
async def notify(req: Request, db: Session = Depends(get_db)):
    """
    微信支付回调的最小示例：为便于本地联调，我们用一个“共享口令”校验代替签名验真。
    生产环境请替换为 v3 的回调签名验真流程。
    """
    token = req.headers.get("X-Notify-Token")
    if token != settings.WECHAT_NOTIFY_TOKEN:
        raise HTTPException(401, "invalid notify token")

    body = await req.json()
    # body 示例：{ "order_id": 123, "status": "SUCCESS", "transaction_id": "...", "amount": 1999 }
    order_id = int(body.get("order_id", 0))
    status = str(body.get("status", ""))
    order = db.get(models.Order, order_id)
    if not order:
        raise HTTPException(404, "order not found")
    if status == "SUCCESS":
        # 记录支付单
        pay = db.query(models.PaymentWeChat).filter_by(order_id=order.id).first()
        if pay:
            pay.status = "success"
            pay.transaction_id = body.get("transaction_id")
            pay.raw_callback_json = json.dumps(body, ensure_ascii=False)
            db.add(pay); db.commit()
        mark_paid_and_grant(db, order)
        return NotifyResult(ok=True)
    return NotifyResult(ok=False)
