import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db
from ..security import get_current_user
from ..schemas import BaziComputeRequest, BaziComputeResponse
from ..services.bazi import compute_bazi_demo, bazi_fingerprint
from .. import models

router = APIRouter(prefix="/bazi", tags=["bazi"])

@router.post("/compute", response_model=BaziComputeResponse)
def compute(req: BaziComputeRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    fp = bazi_fingerprint(req.birth_ts, req.calendar, req.city, req.lat, req.lng)
    row = db.query(models.BaziProfile).filter_by(fingerprint=fp, user_id=user.id).first()
    if row:
        result = json.loads(row.result_json)
        return BaziComputeResponse(profile_id=row.id, **result)
    table, dayun, wuxing = compute_bazi_demo(req.birth_ts, req.calendar, req.city, req.lat, req.lng)
    payload = {"table": table, "dayun": dayun, "wuxing": wuxing}
    row = models.BaziProfile(
        user_id=user.id, birth_ts=req.birth_ts, calendar=req.calendar,
        city=req.city, lat=req.lat, lng=req.lng, fingerprint=fp,
        result_json=json.dumps(payload, ensure_ascii=False)
    )
    db.add(row); db.commit(); db.refresh(row)
    return BaziComputeResponse(profile_id=row.id, **payload)
