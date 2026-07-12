from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8081"]
    )

    data_backend: Literal["supabase", "postgres"] = "supabase"
    auth_mode: Literal["supabase", "oidc", "development"] = "supabase"
    supabase_url: AnyHttpUrl | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None

    database_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10

    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: AnyHttpUrl | None = None

    storage_backend: Literal["supabase", "gcs"] = "supabase"
    gcs_bucket: str | None = None
    gcp_project_id: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str = "Urban Farming"
    admin_email: str = "admin@stratsol.co.za"
    geocoding_user_agent: str = "UrbanFarmingPlatform/1.0"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    def validate_runtime(self) -> None:
        if self.data_backend == "supabase" and not (self.supabase_url and self.supabase_anon_key):
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required in Supabase mode")
        if self.auth_mode == "supabase" and not (self.supabase_url and self.supabase_anon_key):
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_ANON_KEY are required for Supabase authentication"
            )
        if self.data_backend == "postgres" and not self.database_url:
            raise RuntimeError("DATABASE_URL is required in PostgreSQL mode")
        if self.auth_mode == "oidc" and not (
            self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url
        ):
            raise RuntimeError("OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL are required")
        if self.environment == "production" and self.auth_mode == "development":
            raise RuntimeError("Development authentication cannot run in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
