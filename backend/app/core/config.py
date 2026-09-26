"""Environment-driven application settings.

Secrets are never committed; every value here comes from the environment or a
local ``.env`` file (see ``.env.example``).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Estock"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+psycopg://estock:estock@localhost:5432/estock"
    sql_echo: bool = False

    # Auth
    secret_key: str = "dev-only-insecure-secret-change-me"
    access_token_ttl_minutes: int = 60 * 12
    jwt_algorithm: str = "HS256"
    password_reset_ttl_minutes: int = 60

    # Rate limits for anonymous endpoints (PRD 20).  Sliding windows, kept in
    # process memory; 0 disables a limit.
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300
    public_rate_limit: int = 30
    public_rate_window_seconds: int = 60

    # Background jobs / notifications
    redis_url: str = "redis://localhost:6379/0"
    reminder_lookahead_days: int = 7

    # Trial / subscription defaults (platform admin configurable at runtime)
    default_trial_days: int = 14

    # Files
    storage_backend: str = "local"
    storage_local_root: str = "./var/uploads"
    max_upload_bytes: int = 10 * 1024 * 1024

    # Localisation
    default_currency: str = "ETB"
    default_locale: str = "en"
    default_country_code: str = "+251"

    # Public storefront
    public_base_url: str = "http://localhost:3000"
    #: Comma-separated browser origins allowed to call the API. The defaults
    #: cover local development; deployments set this explicitly.
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        # `make mobile-web` serves the Flutter app here for browser testing.
        "http://localhost:8090,http://127.0.0.1:8090"
    )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        origins = {o.strip() for o in self.cors_origins.split(",") if o.strip()}
        origins.add(self.public_base_url.rstrip("/"))
        return sorted(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
