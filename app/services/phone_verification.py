# app/services/phone_verification.py
"""
Phone verification code service using Redis for storage.
Handles code generation, validation, and rate limiting.
"""
import random
import string
import time
from datetime import datetime
from typing import Tuple, Optional
from redis import Redis


def generate_code() -> str:
    """Generate a 6-digit verification code"""
    return ''.join(random.choices(string.digits, k=6))


def can_send_code(redis: Redis, phone: str, ip_address: str) -> Tuple[bool, Optional[str]]:
    """
    Check if verification code can be sent

    Checks:
    1. Phone rate limit (60 seconds between sends)
    2. IP rate limit (max 3 requests per 60 seconds)
    3. Daily limit (max 10 requests per day per phone)

    Args:
        redis: Redis client
        phone: Phone number
        ip_address: Client IP address

    Returns:
        (can_send: bool, error_message: Optional[str])
    """
    return can_send_code_with_limits(redis, phone, ip_address)


def can_send_code_with_limits(
    redis: Redis,
    phone: str,
    ip_address: str,
    *,
    phone_cooldown_seconds: int = 60,
    daily_limit: int = 10,
    ip_window_seconds: int = 60,
    ip_window_limit: int = 3,
) -> Tuple[bool, Optional[str]]:
    """Check whether a phone code can be sent with configurable limits."""
    # 1. Check phone rate limit
    rate_key = f"phone:ratelimit:{phone}"
    if redis.exists(rate_key):
        ttl = redis.ttl(rate_key)
        return False, f"请求过于频繁，请 {ttl} 秒后重试"

    # 2. Check IP rate limit
    ip_key = f"phone:ratelimit:ip:{ip_address}"
    ip_count = redis.get(ip_key)
    if ip_count and int(ip_count) >= ip_window_limit:
        ttl = redis.ttl(ip_key)
        return False, f"该 IP 请求过于频繁，请 {ttl} 秒后重试"

    # 3. Check daily limit
    today = datetime.now().strftime("%Y%m%d")
    daily_key = f"phone:daily:{phone}:{today}"
    daily_count = redis.get(daily_key)
    if daily_count and int(daily_count) >= daily_limit:
        return False, f"今日请求次数已达上限（{daily_limit}次），请明天再试"

    return True, None


def save_verification_code(
    redis: Redis,
    phone: str,
    code: str,
    ip_address: str,
    purpose: str = "login",
    expire_seconds: int = 300,
    phone_cooldown_seconds: int = 60,
    ip_window_seconds: int = 60,
) -> None:
    """
    Save verification code to Redis and update rate limit counters

    Args:
        redis: Redis client
        phone: Phone number
        code: Verification code
        ip_address: Client IP address
        purpose: Code purpose (login, bind, verify)
        expire_seconds: Code expiration time in seconds (default: 300 = 5 minutes)
    """
    # Save verification code (5 minutes expiration)
    code_key = f"phone:code:{phone}:{purpose}"
    redis.setex(code_key, expire_seconds, code)

    # Initialize attempt counter to 0
    attempts_key = f"phone:attempts:{phone}:{purpose}"
    redis.setex(attempts_key, expire_seconds, 0)

    # Set phone rate limit
    rate_key = f"phone:ratelimit:{phone}"
    redis.setex(rate_key, phone_cooldown_seconds, int(time.time()))

    # Increment IP counter
    ip_key = f"phone:ratelimit:ip:{ip_address}"
    redis.incr(ip_key)
    redis.expire(ip_key, ip_window_seconds)

    # Increment daily counter (24 hours)
    today = datetime.now().strftime("%Y%m%d")
    daily_key = f"phone:daily:{phone}:{today}"
    redis.incr(daily_key)
    redis.expire(daily_key, 86400)


def verify_code(
    redis: Redis,
    phone: str,
    code: str,
    purpose: str = "login"
) -> Tuple[bool, str]:
    """
    Verify verification code

    Args:
        redis: Redis client
        phone: Phone number
        code: Verification code to verify
        purpose: Code purpose (login, bind, verify)

    Returns:
        (success: bool, message: str)
    """
    code_key = f"phone:code:{phone}:{purpose}"
    attempts_key = f"phone:attempts:{phone}:{purpose}"

    # Check if code exists
    stored_code = redis.get(code_key)
    if not stored_code:
        return False, "验证码已过期或不存在，请重新获取"

    # Check attempt count
    attempts = int(redis.get(attempts_key) or 0)
    if attempts >= 5:
        # Delete code to prevent further attempts
        redis.delete(code_key)
        redis.delete(attempts_key)
        return False, "验证码已失效，请重新获取"

    # Verify code
    if stored_code != code:
        # Increment attempt counter
        redis.incr(attempts_key)
        remaining = 5 - (attempts + 1)
        if remaining > 0:
            return False, f"验证码错误，还剩 {remaining} 次尝试机会"
        else:
            # Max attempts reached, delete code
            redis.delete(code_key)
            redis.delete(attempts_key)
            return False, "验证码已失效，请重新获取"

    # Verification successful, delete code (prevent reuse)
    redis.delete(code_key)
    redis.delete(attempts_key)
    return True, "验证成功"


def validate_china_phone(phone: str) -> bool:
    """
    Validate Chinese mainland phone number format

    Args:
        phone: Phone number string

    Returns:
        True if valid, False otherwise
    """
    import re
    return bool(re.match(r'^1[3-9]\d{9}$', phone))
