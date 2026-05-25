# app/services/sms.py
"""
SMS service for sending verification codes via Tencent Cloud SMS.
Supports development mode where codes are logged instead of sent.
"""
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class TencentSMSService:
    """Tencent Cloud SMS service with development mode support"""

    def __init__(
        self,
        secret_id: Optional[str] = None,
        secret_key: Optional[str] = None,
        app_id: Optional[str] = None,
        sign: str = "易凡文化",
        template_id: Optional[str] = None,
        dev_mode: bool = True
    ):
        """
        Initialize SMS service

        Args:
            secret_id: Tencent Cloud Secret ID
            secret_key: Tencent Cloud Secret Key
            app_id: SMS Application ID
            sign: SMS signature (default: 易凡文化)
            template_id: SMS template ID
            dev_mode: If True, log codes instead of sending SMS
        """
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.app_id = app_id
        self.sign = sign
        self.template_id = template_id
        self.dev_mode = dev_mode

        # Check if production mode is properly configured
        if not dev_mode:
            if not all([secret_id, secret_key, app_id, template_id]):
                logger.warning(
                    "SMS service missing credentials, falling back to dev mode"
                )
                self.dev_mode = True

    async def send_verification_code(
        self,
        phone: str,
        code: str
    ) -> Tuple[bool, str]:
        """
        Send verification code SMS

        Args:
            phone: Phone number (11 digits)
            code: Verification code (6 digits)

        Returns:
            (success: bool, message: str)
        """
        # Development mode: log the code
        if self.dev_mode:
            logger.info(
                f"[DEV MODE] SMS verification code for {phone}: {code} "
                f"(valid for 5 minutes)"
            )
            return True, f"验证码已发送（开发模式：{code}）"

        # Production mode: send via Tencent Cloud
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
            from tencentcloud.sms.v20210111 import sms_client, models

            # Initialize client
            cred = credential.Credential(self.secret_id, self.secret_key)
            client = sms_client.SmsClient(cred, "ap-guangzhou")

            # Build request
            req = models.SendSmsRequest()
            req.SmsSdkAppId = self.app_id
            req.SignName = self.sign
            req.TemplateId = self.template_id
            req.TemplateParamSet = [code, "5"]  # code, expire_minutes
            req.PhoneNumberSet = [f"+86{phone}"]

            # Send SMS
            resp = client.SendSms(req)

            # Check response
            if resp.SendStatusSet and len(resp.SendStatusSet) > 0:
                status = resp.SendStatusSet[0]
                if status.Code == "Ok":
                    logger.info(f"SMS sent successfully to {phone}")
                    return True, "验证码已发送"
                else:
                    error_msg = status.Message or "Unknown error"
                    logger.error(f"SMS send failed: {error_msg}")
                    return False, f"发送失败：{error_msg}"
            else:
                logger.error("SMS send failed: empty response")
                return False, "发送失败：服务响应异常"

        except TencentCloudSDKException as e:
            logger.error(f"Tencent Cloud SDK error: {e}")
            return False, f"发送失败：{str(e)}"
        except ImportError:
            logger.error("tencentcloud-sdk-python not installed")
            return False, "发送失败：短信服务未配置"
        except Exception as e:
            logger.error(f"Unexpected error sending SMS: {e}")
            return False, f"发送失败：{str(e)}"


def create_sms_service(config) -> TencentSMSService:
    """
    Factory function to create SMS service from config

    Args:
        config: Settings object from app.config

    Returns:
        TencentSMSService instance
    """
    # Determine if we're in dev mode
    dev_mode = (
        config.is_development() or
        not all([
            config.tencent_sms_secret_id,
            config.tencent_sms_secret_key,
            config.tencent_sms_app_id,
            config.tencent_sms_template_id
        ])
    )

    return TencentSMSService(
        secret_id=config.tencent_sms_secret_id,
        secret_key=config.tencent_sms_secret_key,
        app_id=config.tencent_sms_app_id,
        sign=config.tencent_sms_sign,
        template_id=config.tencent_sms_template_id,
        dev_mode=dev_mode
    )
