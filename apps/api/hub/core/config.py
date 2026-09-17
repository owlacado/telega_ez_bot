from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / ".env", extra="ignore"
    )
    database_url: str = "postgresql+asyncpg://hub:hub_local_only@127.0.0.1:5436/technician_hub"
    app_env: str = "development"
