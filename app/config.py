# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    app_name: str = "Bazi AI Backend"
    debug: bool = True
    database_url: str = "mysql+pymysql://root:123456@127.0.0.1:3306/fate"

    jwt_secret: str = Field(default="change-me", validation_alias="JWT_SECRET")
    jwt_alg: str = Field(default="HS256", validation_alias="JWT_ALG")
    jwt_expire_minutes: int = Field(default=7*24*60, validation_alias="JWT_EXPIRE_MINUTES")

    wx_appid: str = Field(default="", validation_alias="WX_APPID")
    wx_secret: str = Field(default="", validation_alias="WX_SECRET")

    cors_allow_origins: str = Field(default="*", validation_alias="CORS_ALLOW_ORIGINS")

    # 关键：声明 dev_mode，并映射到 DEV_MODE 环境变量
    dev_mode: bool = Field(default=False, validation_alias="DEV_MODE")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",      # 避免未来新增 env 未定义时直接报错（可选）
        env_prefix="",       # 不加前缀，直接读取上述 alias
    )

settings = Settings()
