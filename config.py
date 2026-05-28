from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    monitor_users: str
    token_secret: str
    bind_host: str = "0.0.0.0"
    bind_port: int = 8000
    poll_interval: float = 2.0
    log_level: str = "INFO"

    @property
    def users(self) -> dict[str, str]:
        out = {}
        for pair in self.monitor_users.split(","):
            if ":" in pair:
                u, h = pair.split(":", 1)
                out[u.strip()] = h.strip()
        return out


def get_settings() -> Settings:
    return Settings()
