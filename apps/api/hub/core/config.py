from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )
    database_url: str = "postgresql+asyncpg://hub:hub_local_only@127.0.0.1:5436/technician_hub"
    app_env: str = "development"
    debug: bool = False
    app_version: str = "0.3.0"
    release_commit: str = "development"
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    allow_fake_providers: bool = False
    session_lifetime_seconds: int = Field(default=28800, ge=60, le=86400)
    work_report_session_seconds: int = Field(default=900, ge=600, le=900)

    google_mode: Literal["disabled", "real", "fake"] = "disabled"
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    google_calendar_credential_encryption_key: SecretStr | None = None
    google_oauth_manager_limit: int = Field(default=5, ge=1, le=1000)
    google_oauth_manager_window_seconds: int = Field(default=900, ge=1, le=86400)
    google_oauth_global_limit: int = Field(default=20, ge=1, le=10000)
    google_oauth_global_window_seconds: int = Field(default=3600, ge=1, le=86400)
    google_manual_manager_limit: int = Field(default=6, ge=1, le=1000)
    google_manual_manager_window_seconds: int = Field(default=600, ge=1, le=86400)
    google_manual_global_limit: int = Field(default=30, ge=1, le=10000)
    google_manual_global_window_seconds: int = Field(default=3600, ge=1, le=86400)
    google_oauth_attempt_retention_days: int = Field(default=7, ge=1, le=365)

    schedule_delivery_enabled: bool = False
    schedule_timed_auto_enabled: bool = False
    schedule_payload_encryption_key: SecretStr | None = None
    schedule_auto_delivery_local_time: str = Field(
        default="20:00", pattern=r"^(?:[01][0-9]|2[0-2]):[0-5][0-9]$"
    )

    telegram_mode: Literal["disabled", "real", "fake"] = "disabled"
    telegram_bot_token: SecretStr | None = None
    telegram_token_file: str | None = None
    telegram_expected_bot_username: str | None = None
    telegram_expected_bot_id: int | None = None
    telegram_invite_seconds: int = Field(default=900, ge=60, le=3600)
    telegram_sender_minute_limit: int = Field(default=30, ge=1, le=1000)
    telegram_sender_burst_limit: int = Field(default=10, ge=1, le=1000)
    telegram_sender_burst_seconds: int = Field(default=10, ge=1, le=3600)
    telegram_global_minute_limit: int = Field(default=300, ge=1, le=10000)
    telegram_processed_update_retention_days: int = Field(default=7, ge=7, le=365)

    @model_validator(mode="before")
    @classmethod
    def empty_optional_configuration(cls, values):
        for key in (
            "google_client_id",
            "google_client_secret",
            "google_oauth_redirect_uri",
            "google_calendar_credential_encryption_key",
            "telegram_expected_bot_id",
            "telegram_expected_bot_username",
            "telegram_token_file",
            "telegram_bot_token",
            "schedule_payload_encryption_key",
        ):
            if values.get(key) == "":
                values[key] = None
        return values

    @model_validator(mode="after")
    def local_http_only(self) -> "Settings":
        try:
            database = make_url(self.database_url)
        except Exception:
            raise ValueError("DATABASE_URL must be a valid PostgreSQL async URL.") from None
        if (
            database.drivername != "postgresql+asyncpg"
            or not database.database
            or not database.host
            or not database.username
            or database.password is None
        ):
            raise ValueError("DATABASE_URL must include PostgreSQL async host and credentials.")
        if self.debug and self.app_env not in {"development", "test"}:
            raise ValueError("Debug mode is forbidden outside development/test.")
        if not self.allowed_origins:
            raise ValueError("At least one exact application origin is required.")
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
                or parsed.password
                or not parsed.hostname
                or parsed.hostname == "*"
            ):
                raise ValueError("Origins must be exact HTTP(S) origins without paths.")
            try:
                parsed.hostname.encode("ascii")
            except UnicodeEncodeError:
                raise ValueError("Origins must use their ASCII IDNA host form.") from None
            if parsed.scheme == "http" and (
                self.app_env not in {"development", "test"}
                or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError("HTTP is allowed only on loopback for local development/test.")
        if self.telegram_mode == "fake" or self.google_mode == "fake":
            if (
                self.app_env != "test"
                or not self.allow_fake_providers
                or database.database != "technician_hub_test"
                or database.host not in {"127.0.0.1", "localhost", "test-db"}
                or not str(database.password).endswith("_test_only")
            ):
                raise ValueError(
                    "Fake providers require explicit opt-in and an isolated "
                    "disposable test database."
                )
        if self.app_env not in {"development", "test"} and database.password in {
            "hub_local_only",
            "hub_test_only",
            "password",
            "changeme",
        }:
            raise ValueError("Production database credentials must not use sample passwords.")
        if self.telegram_expected_bot_username:
            import re

            if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", self.telegram_expected_bot_username):
                raise ValueError("Invalid configured bot username.")
        if self.telegram_expected_bot_id is not None and self.telegram_expected_bot_id <= 0:
            raise ValueError("Expected bot identity must be positive.")
        if self.google_mode != "disabled":
            from hub.core.secrets import SecretCipher

            if not self.google_calendar_credential_encryption_key:
                raise ValueError("Google credential encryption key is required.")
            SecretCipher(self.google_calendar_credential_encryption_key.get_secret_value())
            if self.app_env not in {
                "development",
                "test",
            } and self.google_calendar_credential_encryption_key.get_secret_value() in {
                "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                "h296Hlwktt4byynveKVcQuxX7eN8ty77nlor-a3Omyc=",
            }:
                raise ValueError("Production Google credential encryption key is a test key.")
        if self.schedule_delivery_enabled:
            from hub.core.secrets import SecretCipher

            if not self.schedule_payload_encryption_key:
                raise ValueError("Schedule payload encryption key is required.")
            SecretCipher(self.schedule_payload_encryption_key.get_secret_value())
            if self.app_env not in {
                "development",
                "test",
            } and self.schedule_payload_encryption_key.get_secret_value() in {
                "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                "1ajUDMfGL53YFA8iShNsP-xjjA0YvMk_0QPLePP2uKs=",
            }:
                raise ValueError("Production schedule payload encryption key is a test key.")
            if self.telegram_mode == "disabled" or not self.telegram_expected_bot_id:
                raise ValueError("Schedule delivery requires configured Telegram identity.")
            if self.google_mode == "disabled":
                raise ValueError("Schedule delivery requires configured Google Calendar access.")
        if self.google_mode == "real":
            if not all(
                (self.google_client_id, self.google_client_secret, self.google_oauth_redirect_uri)
            ):
                raise ValueError("Google OAuth configuration is incomplete.")
            redirect = urlparse(self.google_oauth_redirect_uri)
            if (
                redirect.scheme not in {"https", "http"}
                or redirect.query
                or redirect.fragment
                or redirect.username
                or redirect.path != "/api/calendar-connections/google/callback"
                or (
                    redirect.scheme == "http"
                    and (
                        self.app_env not in {"development", "test"}
                        or redirect.hostname not in {"localhost", "127.0.0.1"}
                    )
                )
            ):
                raise ValueError("Invalid Google OAuth redirect URI.")
            if f"{redirect.scheme}://{redirect.netloc}" not in self.allowed_origins:
                raise ValueError("Google callback must use a configured application origin.")
        return self

    @property
    def allowed_hosts(self) -> list[str]:
        """Exact public origin hosts plus local container-health probe hosts."""
        return sorted(
            {
                "localhost",
                "127.0.0.1",
                "api",
                *(urlparse(origin).hostname for origin in self.allowed_origins),
            }
        )
