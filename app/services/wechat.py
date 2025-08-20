import httpx

WX_API = "https://api.weixin.qq.com/sns/jscode2session"

async def jscode2session(appid: str, secret: str, js_code: str):
    params = {
        "appid": appid,
        "secret": secret,
        "js_code": js_code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(WX_API, params=params)
        data = r.json()
        return data