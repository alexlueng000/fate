# app/services/captcha.py
"""
Captcha verification service for Tencent Cloud Captcha.
Supports development mode where captcha is skipped.
"""
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class TencentCaptchaService:
    """Tencent Cloud Captcha verification service"""

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        secret_id: Optional[str] = None,
        secret_key: Optional[str] = None,
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
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.enabled = enabled

        # Check if captcha is properly configured
        if enabled and (not app_id or not app_secret or not secret_id or not secret_key):
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
            from tencentcloud.common import credential
            from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
            from tencentcloud.captcha.v20190722 import captcha_client, models

            cred = credential.Credential(self.secret_id, self.secret_key)
            client = captcha_client.CaptchaClient(cred, "ap-guangzhou")

            req = models.DescribeCaptchaResultRequest()
            req.CaptchaType = 9
            req.Ticket = ticket
            req.UserIp = user_ip
            req.Randstr = randstr
            req.CaptchaAppId = int(self.app_id or 0)
            req.AppSecretKey = self.app_secret

            resp = client.DescribeCaptchaResult(req)
            captcha_code = getattr(resp, "CaptchaCode", None)
            captcha_msg = getattr(resp, "CaptchaMsg", None) or "验证失败"

            if captcha_code == 1 or str(captcha_code) == "1":
                evil_level = getattr(resp, "EvilLevel", 0) or 0
                if evil_level > 80:
                    logger.warning(f"High evil_level detected: {evil_level}")
                    return False, "验证失败，请重试"

                logger.info(f"Captcha verified successfully (evil_level: {evil_level})")
                return True, "验证通过"

            logger.warning(
                "Captcha verification failed: code=%s message=%s",
                captcha_code,
                captcha_msg,
            )
            return False, f"验证失败：{captcha_msg}"

        except TencentCloudSDKException as e:
            logger.error(f"Tencent Cloud Captcha SDK error: {e}")
            return False, f"验证失败：{e.message or str(e)}"
        except ImportError:
            logger.error("tencentcloud-sdk-python not installed")
            return False, "验证服务未配置"
        except ValueError:
            logger.error("Invalid Tencent Captcha App ID: %s", self.app_id)
            return False, "验证码配置错误"
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
        secret_id=config.tencent_captcha_secret_id or config.tencent_sms_secret_id,
        secret_key=config.tencent_captcha_secret_key or config.tencent_sms_secret_key,
        enabled=config.captcha_enabled
    )
