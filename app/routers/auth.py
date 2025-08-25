# app/api/auth.py
from fastapi import APIRouter, HTTPException
from app.schemas import LoginIn, LoginOut
# from app.security import jwt_encode
from app.services.wechat import jscode2session
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn):
    # 本地开发直通：js_code=dev 时伪造 openid，便于小程序端先联调
    if body.js_code == "dev":
        openid = "oDEV-openid-123456"
        # token = jwt_encode({"sub": openid}, settings.jwt_secret, settings.jwt_alg, settings.jwt_expire_minutes)
        return LoginOut(openid=openid, unionid=None, session_key=None, access_token=token)

    # 真机环境：调用微信 jscode2session
    data = await jscode2session(settings.wx_appid, settings.wx_secret, body.js_code)

    # 微信错误处理
    if "errcode" in data and data["errcode"] != 0:
        # 常见：40029 invalid code, 40163 code been used, 40125 invalid appsecret
        raise HTTPException(status_code=400, detail={"errcode": data["errcode"], "errmsg": data.get("errmsg")})

    openid = data.get("openid")
    session_key = data.get("session_key")
    unionid = data.get("unionid")

    if not openid or not session_key:
        raise HTTPException(status_code=400, detail="Missing openid/session_key from WeChat")

    # TODO: 这里可落库：若无则创建用户，有则更新 last_login、昵称等
    # await upsert_user(openid=openid, nickname=body.nickname)

    token = jwt_encode({"sub": openid}, settings.jwt_secret, settings.jwt_alg, settings.jwt_expire_minutes)
    return LoginOut(openid=openid, unionid=unionid, session_key=session_key, access_token=token)
