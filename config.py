from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bind_host: str = "0.0.0.0"
    bind_port: int = 8000
    poll_interval: float = 2.0
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
