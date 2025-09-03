# app/core/security.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union
from uuid import uuid4

from jose import JWTError, jwt

from argon2 import PasswordHasher
from argon2.low_level import Type as Argon2Type
from argon2.exceptions import VerifyMismatchError, VerificationError

from app.config import settings

# =========================
# 配置
# =========================
def _get(name_lower: str, name_upper: str, default: Any) -> Any:
    if hasattr(settings, name_lower):
        return getattr(settings, name_lower)
    if hasattr(settings, name_upper):
        return getattr(settings, name_upper)
    return default

SECRET_KEY: str = _get("jwt_secret", "JWT_SECRET", "change-me")  # 部署务必覆盖
ALGORITHM: str = _get("jwt_alg", "JWT_ALG", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(_get("jwt_expire_minutes", "JWT_EXPIRE_MINUTES", 7 * 24 * 60))
# CLOCK_SKEW_LEEWAY_SECONDS: int = int(_get("jwt_clock_skew_leeway", "JWT_CLOCK_SKEW_LEEWAY", 30))

# =========================
# JWT
# =========================
def create_access_token(
    subject: Union[str, int],
    *,
    expires_minutes: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid4().hex,
    }
    if extra:
        for k in ("sub", "iat", "exp", "nbf"):
            extra.pop(k, None)
        to_encode.update(extra)
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Dict[str, Any]:
    try:
        payload: Dict[str, Any] = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_aud": False},
            # leeway=CLOCK_SKEW_LEEWAY_SECONDS,
        )
        return payload
    except JWTError as e:
        raise e

# =========================
# 密码哈希（Argon2id）
# =========================
_ph = PasswordHasher(
    time_cost=2,
    memory_cost=19456,   # ≈19 MB
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Argon2Type.ID,
)

def hash_password(plain: str) -> str:
    if not plain or len(plain) < 6:
        raise ValueError("密码长度过短（至少 6 位）")
    return _ph.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError):
        return False

def password_needs_rehash(hashed: str) -> bool:
    try:
        return _ph.check_needs_rehash(hashed)
    except Exception:
        return True
