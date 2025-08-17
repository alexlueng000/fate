# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic_settings import BaseSettings, SettingsConfigDict
import httpx, time
from ..db import get_db
from .. import models
from ..schemas import LoginRequest, TokenResponse
from ..security import create_token

router = APIRouter(prefix="/auth", tags=["auth"])

class Settings(BaseSettings):
    DEV_MODE: bool = False
    WX_APPID: str = ""
    WX_SECRET: str = ""
    JWT_EXPIRE_MINUTES: int = 7 * 24 * 60
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

async def wechat_code2session(js_code: str) -> dict:
    """
    调用微信 jscode2session，返回 {openid, session_key, unionid?}
    出错抛 HTTPException。
    """
    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": settings.WX_APPID,
        "secret": settings.WX_SECRET,
        "js_code": js_code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(url, params=params)
    data = r.json()
    # 正常返回包含 openid；失败返回 errcode/errmsg
    if "openid" not in data:
        raise HTTPException(
            status_code=400,
            detail={"error": "weixin_error", "payload": data}
        )
    return data

def upsert_user_by_openid(db: Session, openid: str, nickname: str | None, avatar: str | None, unionid: str | None = None):
    """ 幂等创建/更新用户。 """
    user = db.query(models.User).filter_by(openid=openid).first()
    if not user:
        user = models.User(openid=openid, nickname=nickname, avatar=avatar, unionid=unionid)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user, True
    # 轻度更新（不强制覆盖已有昵称/头像）
    changed = False
    if nickname and (user.nickname != nickname):
        user.nickname = nickname; changed = True
    if avatar and (user.avatar != avatar):
        user.avatar = avatar; changed = True
    if unionid and (not user.unionid):
        user.unionid = unionid; changed = True
    if changed:
        db.commit()
        db.refresh(user)
    return user, False

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """
    - DEV_MODE=True 且 js_code in {"dev","local","test"} 时，本地直发 token（不调微信）
    - 否则：调用微信 code2session 获取 openid/unionid，再签发 token
    返回：token 及可选的过期时间，前端存储后即可带 Authorization: Bearer <token>
    """
    js_code = (req.js_code or "").strip()
    if not js_code:
        raise HTTPException(400, "invalid js_code")

    # 本地模拟登录
    if settings.DEV_MODE and js_code in {"dev", "local", "test"}:
        openid = f"openid_local_{int(time.time())}"
        user, _ = upsert_user_by_openid(db, openid, req.nickname, req.avatar)
        token = create_token(user.id)
        return TokenResponse(token=token, expires_in=settings.JWT_EXPIRE_MINUTES * 60, mode="dev")

    # 真实微信登录
    session = await wechat_code2session(js_code)
    openid = session["openid"]
    unionid = session.get("unionid")
    # 可选：保存 session_key（若后续要做解密手机号等）
    # session_key = session.get("session_key")

    user, _ = upsert_user_by_openid(db, openid, req.nickname, req.avatar, unionid=unionid)
    token = create_token(user.id)
    return TokenResponse(token=token, expires_in=settings.JWT_EXPIRE_MINUTES * 60, mode="prod")
