from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / ".env", extra="ignore"
    )
    database_url: str = "postgresql+asyncpg://hub:hub_local_only@127.0.0.1:5436/technician_hub"
    app_env: str = "development"
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    session_lifetime_seconds: int = Field(default=28800, ge=60, le=86400)

    telegram_mode: Literal["disabled", "real", "fake"] = "disabled"
    telegram_bot_token: SecretStr | None = None
    telegram_token_file: str | None = None
    telegram_expected_bot_username: str | None = None
    telegram_expected_bot_id: int | None = None
    telegram_invite_seconds: int = Field(default=900, ge=60, le=3600)

    @model_validator(mode="before")
    @classmethod
    def empty_optional_configuration(cls, values):
        for key in (
            "telegram_expected_bot_id",
            "telegram_expected_bot_username",
            "telegram_token_file",
            "telegram_bot_token",
        ):
            if values.get(key) == "":
                values[key] = None
        return values

    @model_validator(mode="after")
    def local_http_only(self) -> "Settings":
        if not self.cookie_secure and self.app_env not in {"development", "test"}:
            raise ValueError("Secure cookies are required outside local development/test.")
        for origin in self.allowed_origins:
            parsed = urlparse(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ValueError("Origins must be exact HTTP(S) origins without paths.")
            if parsed.scheme == "http" and (
                self.app_env not in {"development", "test"}
                or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError("HTTP is allowed only on loopback for local development/test.")
        if self.telegram_mode == "fake":
            from sqlalchemy.engine import make_url

            db = make_url(self.database_url)
            if (
                self.app_env != "test"
                or db.database != "technician_hub_test"
                or db.host not in {"127.0.0.1", "localhost", "test-db", "db"}
            ):
                raise ValueError("Fake providers are restricted to the isolated test database.")
        if self.telegram_expected_bot_username:
            import re

            if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", self.telegram_expected_bot_username):
                raise ValueError("Invalid configured bot username.")
        if self.telegram_expected_bot_id is not None and self.telegram_expected_bot_id <= 0:
            raise ValueError("Expected bot identity must be positive.")
        return self
