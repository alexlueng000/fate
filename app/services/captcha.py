# app/services/captcha.py
"""
Captcha verification service for Tencent Cloud Captcha.
Supports development mode where captcha is skipped.
"""
import logging
import hmac
import hashlib
import json
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class TencentCaptchaService:
    """Tencent Cloud Captcha verification service"""

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        enabled: bool = True
    ):
        """
        Initialize captcha service

        Args:
            app_id: Tencent Captcha App ID
            app_secret: Tencent Captcha App Secret
            enabled: If False, skip captcha verification (dev mode)
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.enabled = enabled

        # Check if captcha is properly configured
        if enabled and (not app_id or not app_secret):
            logger.warning(
                "Captcha enabled but credentials missing, disabling captcha"
            )
            self.enabled = False

    async def verify_captcha(
        self,
        ticket: str,
        randstr: str,
        user_ip: str
    ) -> Tuple[bool, str]:
        """
        Verify captcha ticket from frontend

        Args:
            ticket: Captcha ticket from frontend
            randstr: Random string from frontend
            user_ip: User's IP address

        Returns:
            (success: bool, message: str)
        """
        # Development mode: skip verification
        if not self.enabled:
            logger.info("[DEV MODE] Captcha verification skipped")
            return True, "验证通过（开发模式）"

        if not ticket or not randstr:
            return False, "验证码参数缺失"

        try:
            import requests

            # Build verification request
            url = "https://ssl.captcha.qq.com/ticket/verify"
            params = {
                "aid": self.app_id,
                "AppSecretKey": self.app_secret,
                "Ticket": ticket,
                "Randstr": randstr,
                "UserIP": user_ip,
            }

            # Send verification request
            resp = requests.get(url, params=params, timeout=5)
            data = resp.json()

            # Check response
            # response: 1 = success, 0 = failure
            # evil_level: 0-100, higher = more suspicious
            if data.get("response") == 1:
                evil_level = data.get("evil_level", 0)
                if evil_level > 80:
                    logger.warning(f"High evil_level detected: {evil_level}")
                    return False, "验证失败，请重试"

                logger.info(f"Captcha verified successfully (evil_level: {evil_level})")
                return True, "验证通过"
            else:
                err_msg = data.get("err_msg", "验证失败")
                logger.warning(f"Captcha verification failed: {err_msg}")
                return False, f"验证失败：{err_msg}"

        except requests.RequestException as e:
            logger.error(f"Captcha verification request failed: {e}")
            return False, "验证服务暂时不可用"
        except Exception as e:
            logger.error(f"Unexpected error during captcha verification: {e}")
            return False, "验证失败，请重试"


def create_captcha_service(config) -> TencentCaptchaService:
    """
    Factory function to create captcha service from config

    Args:
        config: Settings object from app.config

    Returns:
        TencentCaptchaService instance
    """
    return TencentCaptchaService(
        app_id=config.tencent_captcha_app_id,
        app_secret=config.tencent_captcha_app_secret,
        enabled=config.captcha_enabled
    )
