from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "DataSentry"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://datasentry:datasentry@localhost:5432/datasentry"
    secret_key: str = Field("dev-insecure-change-me-0123456789abcdef", min_length=32)
    access_token_ttl_minutes: int = 12 * 60

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    static_dir: str | None = None

    storage_backend: Literal["local", "database"] = "local"
    storage_dir: str = "./data/storage"

    max_upload_mb: int = 25
    max_rows: int = 500_000
    max_request_mb: int = 30

    rate_limit_default_per_min: int = 300
    rate_limit_upload_per_min: int = 10
    rate_limit_predictions_per_min: int = 120
    rate_limit_auth_per_min: int = 20

    scheduler_mode: Literal["embedded", "worker", "external", "off"] = "embedded"
    scheduler_poll_seconds: int = 15
    cron_secret: str | None = None

    allow_registration: bool = True
    demo_mode_enabled: bool = True
    demo_workspace_ttl_hours: int = 24
    max_demo_workspaces: int = 200

    prediction_feature_logging: Literal["none", "aggregate", "full"] = "aggregate"
    prediction_retention_days: int = 90

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    @field_validator("database_url")
    @classmethod
    def _driver(cls, v: str) -> str:
        # Managed providers hand out postgres:// URLs; SQLAlchemy needs an explicit driver.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def check_production_safety(self) -> list[str]:
        problems = []
        if self.is_production and self.secret_key.startswith("dev-"):
            problems.append("SECRET_KEY must be set to a random value in production")
        if self.is_production and "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must list explicit origins in production")
        if self.is_production and self.scheduler_mode == "external" and len(self.cron_secret or "") < 24:
            problems.append("CRON_SECRET must be at least 24 characters when SCHEDULER_MODE=external")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
