from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Default App"
    app_version: str = "0.0.1"
    debug: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
