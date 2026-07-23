from __future__ import annotations

import time
from typing import Optional

from jose import jwt

from app.config import settings


class VodConfigError(RuntimeError):
    pass


def _player_app_id() -> int:
    app_id = settings.tencent_vod_sub_app_id or settings.tencent_vod_app_id
    if not app_id:
        raise VodConfigError("TENCENT_VOD_APP_ID or TENCENT_VOD_SUB_APP_ID is not configured")
    return app_id


def build_player_signature(
    *,
    file_id: str,
    expire_seconds: Optional[int] = None,
    url_expire_seconds: Optional[int] = None,
    rlimit: int = 3,
) -> dict[str, str | int]:
    if not settings.tencent_vod_play_key:
        raise VodConfigError("TENCENT_VOD_PLAY_KEY is not configured")

    now = int(time.time())
    sign_expire_at = now + (expire_seconds or settings.tencent_vod_play_sign_expire_seconds)
    url_expire_at = now + (url_expire_seconds or settings.tencent_vod_url_expire_seconds)
    app_id = _player_app_id()

    payload = {
        "appId": app_id,
        "fileId": str(file_id),
        "currentTimeStamp": now,
        "expireTimeStamp": sign_expire_at,
        "urlAccessInfo": {
            "t": format(url_expire_at, "x"),
            "rlimit": rlimit,
        },
    }

    psign = jwt.encode(payload, settings.tencent_vod_play_key, algorithm="HS256")
    return {
        "appID": app_id,
        "fileID": str(file_id),
        "psign": psign,
        "expires_at": sign_expire_at,
    }
