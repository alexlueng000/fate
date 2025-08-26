# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List, Optional


class Settings(BaseSettings):
    # .env 自动加载；环境变量不区分大小写；忽略未声明字段
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    # -----------------------------
    # App
    # -----------------------------
    app_name: str = "Bazi AI Backend"
    debug: bool = True
    # 逗号分隔或 "*"；main.py 可用 settings.cors_origins_list()
    cors_allow_origins: str = "*"

    # -----------------------------
    # Database (MySQL)
    # -----------------------------
    # 建议用 mysql+pymysql://user:pass@host:3306/dbname
    database_url: str = "mysql+pymysql://root:123456@127.0.0.1:3306/fate"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600    # 秒；1小时回收
    db_pool_timeout: int = 30      # 秒
    db_time_zone: str = "+00:00"   # 生产建议与业务一致，如 "+08:00"
    db_strict_mode: bool = True    # 严格模式避免静默截断
    sqlalchemy_echo: bool = False  # 调试 SQL 可设 True，但不要在生产启用

    # -----------------------------
    # Auth / JWT
    # -----------------------------
    jwt_secret: str = "change-me"  # ⚠️ 生产务必覆盖
    jwt_alg: str = "HS256"
    jwt_expire_minutes: int = 7 * 24 * 60
    jwt_clock_skew_leeway: int = 30  # 容忍客户端时钟偏差（秒）

    # -----------------------------
    # Business
    # -----------------------------
    # 当前唯一商品编码；与种子数据保持一致
    single_product_code: str = "REPORT_UNLOCK"
    # 开发态固定 openid，配合 js_code=dev 登录
    dev_openid: str = "dev_openid"

    # -----------------------------
    # WeChat Pay v3
    # -----------------------------
    # 'prod'：严格验签/解密；'dev'：跳过验签便于联调
    wechat_pay_mode: str = "dev"
    # 32字节 APIv3 Key；生产必填
    wechat_api_v3_key: Optional[str] = None
    # 平台公钥（或证书）PEM 内容（任选其一：PEM 或 Path）
    wechat_platform_public_key_pem: Optional[str] = None
    wechat_platform_public_key_path: Optional[str] = None

    # -----------------------------
    # Helpers
    # -----------------------------
    def cors_origins_list(self) -> List[str]:
        """将 cors_allow_origins 转为列表供 CORS 中间件使用。"""
        if not self.cors_allow_origins or self.cors_allow_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

settings = Settings()
