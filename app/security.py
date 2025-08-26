# app/core/security.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union
from uuid import uuid4

from jose import JWTError, jwt

try:
    # 强烈建议安装：pip install "passlib[bcrypt]"
    from passlib.context import CryptContext  # type: ignore
    _pwd_context: Optional[CryptContext] = CryptContext(
        schemes=["bcrypt"], deprecated="auto"
    )
except Exception:  # pragma: no cover - 可选依赖
    _pwd_context = None

from app.config import settings


# =========================
# 配置与默认值（兼容大小写字段名）
# =========================
def _get(name_lower: str, name_upper: str, default: Any) -> Any:
    if hasattr(settings, name_lower):
        return getattr(settings, name_lower)
    if hasattr(settings, name_upper):
        return getattr(settings, name_upper)
    return default


SECRET_KEY: str = _get("jwt_secret", "JWT_SECRET", "change-me")  # 部署时务必覆盖
ALGORITHM: str = _get("jwt_alg", "JWT_ALG", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(_get("jwt_expire_minutes", "JWT_EXPIRE_MINUTES", 7 * 24 * 60))
CLOCK_SKEW_LEEWAY_SECONDS: int = int(_get("jwt_clock_skew_leeway", "JWT_CLOCK_SKEW_LEEWAY", 30))


# =========================
# JWT
# =========================
def create_access_token(
    subject: Union[str, int],
    *,
    expires_minutes: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """
    生成访问令牌（Bearer）。payload 最少包含:
      - sub: 用户标识（字符串或数字）
      - iat: 签发时间（UTC）
      - exp: 过期时间（UTC）
      - jti: 唯一 ID，便于黑名单/追踪（可选）
    你可以通过 extra 传入其他业务字段，例如 {"is_admin": True}.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid4().hex,
    }
    if extra:
        # 不允许覆盖核心保留字段
        for k in ("sub", "iat", "exp", "nbf"):
            if k in extra:
                extra.pop(k)
        to_encode.update(extra)

    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return token


def decode_token(token: str) -> Dict[str, Any]:
    """
    解析并校验 JWT。返回 payload（dict）。
    - 启用 leeway，容忍少量时钟偏差
    - 校验签名、iat/exp 等标准声明
    - 你可以在上层基于 payload["sub"] 加载用户
    """
    try:
        payload: Dict[str, Any] = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_aud": False},  # 默认不校验 aud
            # leeway=CLOCK_SKEW_LEEWAY_SECONDS,
        )
        return payload
    except JWTError as e:
        # 交由上层转换为 HTTPException(401) 或自定义错误
        raise e


# =========================
# 密码哈希（可选）
# =========================
def get_password_hash(password: str) -> str:
    """
    使用 bcrypt 生成密码哈希。
    需要依赖 passlib[bcrypt]；如果未安装，抛出友好错误。
    """
    if _pwd_context is None:
        raise RuntimeError(
            "Password hashing requires passlib[bcrypt]. Install via: pip install 'passlib[bcrypt]'"
        )
    return _pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    验证明文密码与哈希是否匹配。
    """
    if _pwd_context is None:
        raise RuntimeError(
            "Password hashing requires passlib[bcrypt]. Install via: pip install 'passlib[bcrypt]'"
        )
    return _pwd_context.verify(plain_password, password_hash)
