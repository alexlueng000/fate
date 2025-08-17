from sqlalchemy.orm import Session
from .. import models

def has_entitlement(db: Session, user_id: int, sku: str) -> bool:
    q = db.query(models.Entitlement).filter(
        models.Entitlement.user_id==user_id,
        models.Entitlement.sku==sku,
        models.Entitlement.status=="active"
    )
    return db.query(q.exists()).scalar()
