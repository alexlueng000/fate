from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models
from ..schemas import LoginRequest, TokenResponse
from ..security import create_token

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """
    前端传 js_code → 这里应调用微信 code2session，得到 openid/unionid。
    为了开发快速，这里用 js_code 直接当 openid（MVP）。
    """
    openid = req.js_code.strip()
    if not openid:
        raise HTTPException(400, "invalid js_code")
    user = db.query(models.User).filter_by(openid=openid).first()
    if not user:
        user = models.User(openid=openid, nickname=req.nickname, avatar=req.avatar)
        db.add(user); db.commit(); db.refresh(user)
    token = create_token(user.id)
    return TokenResponse(token=token)
