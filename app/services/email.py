"""
SMTP 邮件发送服务
"""
from __future__ import annotations

import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """SMTP 邮件发送服务"""

    def __init__(self):
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.sender = settings.smtp_sender
        self.use_tls = settings.smtp_use_tls

    async def send_email(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
    ) -> bool:
        """
        异步发送邮件

        Args:
            to: 收件人邮箱
            subject: 邮件主题
            body_html: HTML 正文
            body_text: 纯文本正文（可选）

        Returns:
            是否发送成功
        """
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender
            msg["To"] = to

            # 添加纯文本版本
            if body_text:
                msg.attach(MIMEText(body_text, "plain", "utf-8"))

            # 添加 HTML 版本
            msg.attach(MIMEText(body_html, "html", "utf-8"))

            # 发送邮件
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                start_tls=self.use_tls,
            )

            logger.info(f"邮件发送成功: to={to}, subject={subject}")
            return True

        except Exception as e:
            logger.error(f"邮件发送失败: to={to}, error={e}")
            return False

    async def send_password_reset_code(
        self,
        to: str,
        code: str,
        expires_minutes: int = 15,
    ) -> bool:
        """
        发送密码重置验证码邮件

        Args:
            to: 收件人邮箱
            code: 6位验证码
            expires_minutes: 有效期（分钟）
        """
        subject = "【易凡文化】密码重置验证码"

        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ font-size: 24px; font-weight: bold; color: #a83232; }}
                .code-box {{
                    background: #fff7e8;
                    border: 2px solid #e5c07b;
                    border-radius: 12px;
                    padding: 20px;
                    text-align: center;
                    margin: 20px 0;
                }}
                .code {{
                    font-size: 32px;
                    font-weight: bold;
                    letter-spacing: 8px;
                    color: #a83232;
                }}
                .notice {{ color: #666; font-size: 14px; margin-top: 20px; }}
                .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 30px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">易凡文化</div>
                </div>
                <p>您好，</p>
                <p>您正在重置密码，请使用以下验证码：</p>
                <div class="code-box">
                    <div class="code">{code}</div>
                </div>
                <p class="notice">
                    验证码有效期为 <strong>{expires_minutes} 分钟</strong>，请尽快使用。<br>
                    如果这不是您本人的操作，请忽略此邮件。
                </p>
                <div class="footer">
                    <p>此邮件由系统自动发送，请勿回复。</p>
                    <p>&copy; 易凡文化</p>
                </div>
            </div>
        </body>
        </html>
        """

        body_text = f"""
【易凡文化】密码重置验证码

您好，

您正在重置密码，请使用以下验证码：

{code}

验证码有效期为 {expires_minutes} 分钟，请尽快使用。
如果这不是您本人的操作，请忽略此邮件。

此邮件由系统自动发送，请勿回复。
        """

        return await self.send_email(to, subject, body_html, body_text)


# 单例
email_service = EmailService()
