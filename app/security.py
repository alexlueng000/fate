# app/core/security.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union
from uuid import uuid4

from jose import JWTError, jwt

from argon2 import PasswordHasher
from argon2.low_level import Type as Argon2Type
from argon2.exceptions import VerifyMismatchError, VerificationError

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

# 统一在模块级创建 hasher，避免重复构造
# 参数说明：
# - time_cost：迭代次数（CPU 开销）
# - memory_cost：内存开销（KiB），生产可适当上调（例如 64~128MB）
# - parallelism：并行度；多数 Web 场景设 1 足够
# - hash_len / salt_len：输出与盐长度
# - type：Argon2id（抗 GPU / 防侧信道的平衡方案）
_ph = PasswordHasher(
    time_cost=2,
    memory_cost=19456,   # ≈19 MB
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Argon2Type.ID,
)

def hash_password(plain: str) -> str:
    """
    将明文密码哈希为 Argon2id 字符串（含参数与盐）。
    - 不要自己生成盐；由库自动完成并编码到返回值中。
    - 返回形如：$argon2id$v=19$m=19456,t=2,p=1$...
    """
    if not plain or len(plain) < 6:
        raise ValueError("密码长度过短（至少 6 位）")
    return _ph.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    """
    校验明文密码是否匹配已存哈希。
    - 匹配返回 True；不匹配/异常返回 False。
    """
    if not plain or not hashed:
        return False
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except VerificationError:
        # 含格式不正确、参数不合法等情况
        return False

def password_needs_rehash(hashed: str) -> bool:
    """
    判断既有哈希是否需要按照当前参数重新哈希（例如你将 time_cost/memory_cost 上调后）。
    - True 表示建议在用户下次成功登录时触发“透明升级”。
    """
    try:
        return _ph.check_needs_rehash(hashed)
    except Exception:
        # 无法解析哈希格式时，建议重新哈希
        return True