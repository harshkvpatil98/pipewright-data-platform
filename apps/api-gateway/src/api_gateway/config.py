from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from shared_python.config import parse_cors_origins

# apps/api-gateway/.env — stable path whether cwd is repo root (make dev) or apps/api-gateway (Dockerfile WORKDIR).
_GATEWAY_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_GATEWAY_ENV_FILE, override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_GATEWAY_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Intelligent Data Platform API Gateway"
    app_version: str = "0.2.0"
    app_env: Literal["development", "staging", "production", "test"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://platform:platform@localhost:5432/platform"
    backend_cors_origins: list[str] = ["http://localhost:3000"]
    auth_jwt_secret: str = "change-this-for-production"
    auth_jwt_issuer: str = "intelligent-data-platform"
    auth_jwt_audience: str = "intelligent-data-platform-web"
    auth_access_token_exp_minutes: int = 60
    storage_backend: Literal["local"] = "local"
    upload_root_path: str = "data/uploads"
    max_upload_size_bytes: int = 25 * 1024 * 1024
    allowed_upload_extensions: Annotated[list[str], NoDecode] = ["csv", "xlsx", "json"]
    preview_row_limit: int = 50
    profile_sample_value_limit: int = 5
    # Shared secret for POST /internal/schedules/* (due-schedule executor). If unset, internal routes return 503.
    scheduler_internal_token: str | None = None
    # Stable id for this scheduler worker process (set per replica for lease ownership in multi-instance deploys).
    scheduler_runtime_id: str | None = None
    # Lease duration for automatic schedule claims (seconds). After expiry another worker may reclaim a stalled run.
    scheduler_claim_ttl_seconds: int = Field(default=300, ge=30, le=86400)

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def validate_cors_origins(cls, value):
        return parse_cors_origins(value)

    @field_validator("allowed_upload_extensions", mode="before")
    @classmethod
    def validate_allowed_upload_extensions(cls, value):
        if isinstance(value, list):
            return [str(item).lower().lstrip(".") for item in value]
        if isinstance(value, str):
            return [item.strip().lower().lstrip(".") for item in value.split(",") if item.strip()]
        raise ValueError("Invalid allowed upload extensions value")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
