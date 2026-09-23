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

    app_name: str = "Pipewright API Gateway"
    app_version: str = "0.2.0"
    app_env: Literal["development", "staging", "production", "test"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://platform:platform@localhost:5432/platform"
    # Connection pool sizing. Total connections per process is pool_size + max_overflow,
    # so keep (replicas x that sum) below the database's max_connections.
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    db_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    # Responses at or above this size are gzipped. JSON previews and profiles
    # compress well; below this the CPU cost outweighs the transfer saving.
    gzip_minimum_size_bytes: int = Field(default=1024, ge=0)
    backend_cors_origins: list[str] = ["http://localhost:3000"]
    auth_jwt_secret: str = "change-this-development-only-secret-0123456789"
    # Deliberately still the pre-rebrand name. These two are *validated* on
    # every token decode, so changing them invalidates every issued token --
    # signing out every user of any deployment that did not override them.
    # A cosmetic rename is not worth that; both can be overridden per deployment.
    auth_jwt_issuer: str = "intelligent-data-platform"
    auth_jwt_audience: str = "intelligent-data-platform-web"
    auth_access_token_exp_minutes: int = 60
    storage_backend: Literal["local"] = "local"
    upload_root_path: str = "data/uploads"
    max_upload_size_bytes: int = 25 * 1024 * 1024
    # Every format the ingestion readers handle. The extension is a gate, not a
    # decision: the sniffer reads the bytes and overrules the name, so a
    # workbook renamed `.csv` still loads correctly -- but an extension nobody
    # can read is refused here rather than deep inside a parser.
    allowed_upload_extensions: Annotated[list[str], NoDecode] = [
        "csv", "tsv", "tab", "psv", "txt", "dat",
        "xlsx", "xlsm", "xls",
        "json", "jsonl", "ndjson",
        "xml", "yaml", "yml",
        "parquet", "pq", "avro", "orc",
        "sql",
        "sas7bdat", "dta",
        "gz", "bz2", "xz", "zip",
    ]
    preview_row_limit: int = 50
    profile_sample_value_limit: int = 5
    # Single sign-on. Unset means the platform's own login is the only way in.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    # Space-separated OIDC scopes; the defaults cover identity + email + profile.
    oidc_scopes: str = "openid email profile"
    # JSON object mapping an IdP group/role claim value to a platform role, e.g.
    # '{"data-admins": "admin"}'. Empty means everyone lands on the default role.
    oidc_group_role_map: str = "{}"
    # Role a newly provisioned SSO user gets when no group maps them.
    oidc_default_role: str = "viewer"
    # When false, an SSO sign-in by someone with no account is refused rather
    # than silently creating one.
    oidc_allow_jit: bool = True
    # Where the SSO callback sends the browser after issuing a session. The web
    # app origin; the gateway and web must share a host for the session cookie
    # to carry across (documented in docs/security.md).
    web_base_url: str = "http://localhost:3000"
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
