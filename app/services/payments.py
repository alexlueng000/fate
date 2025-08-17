from sqlalchemy.orm import Session
from .. import models

def create_prepay_stub(db: Session, order: models.Order, openid: str) -> tuple[str, dict]:
    """
    这里演示“预支付”生成。
    真实环境：请求微信支付统一下单接口，得到 prepay_id，然后组装 pay_params 返回给前端调起支付。
    """
    prepay_id = f"mock_prepay_{order.id}"
    pay_params = {
        "timeStamp": "1710000000",
        "nonceStr": "nonce-demo",
        "package": f"prepay_id={prepay_id}",
        "signType": "RSA",
        "paySign": "MOCK_SIGNATURE"
    }
    # 记录一条支付记录
    pay = models.PaymentWeChat(order_id=order.id, prepay_id=prepay_id, amount=order.amount, status="created")
    db.add(pay)
    db.commit()
    db.refresh(pay)
    return prepay_id, pay_params

def mark_paid_and_grant(db: Session, order: models.Order):
    # 标记订单已支付
    order.status = "paid"
    db.add(order); db.commit()
    # 权益开通（简单示例：按 product.sku 生成权益）
    prod = db.get(models.Product, order.product_id)
    if not prod:
        return
    entitlement = models.Entitlement(user_id=order.user_id, sku=prod.sku, quota=None, expires_at=None, status="active")
    db.add(entitlement); db.commit()
