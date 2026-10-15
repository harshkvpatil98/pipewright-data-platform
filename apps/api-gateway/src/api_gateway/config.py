from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from shared_python.config import parse_cors_origins

# apps/api-gateway: the folder the gateway's .env and relative data paths are
# anchored to, whether a process starts in the repository root (make dev, the
# worker script) or in apps/api-gateway (the Docker images' WORKDIR).
_GATEWAY_DIR = Path(__file__).resolve().parents[2]
_GATEWAY_ENV_FILE = _GATEWAY_DIR / ".env"
load_dotenv(_GATEWAY_ENV_FILE, override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_GATEWAY_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Pipewright API Gateway"
    app_version: str = "1.0.0"
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
    # Log any SQL statement that runs for at least this many milliseconds. 0
    # turns it off entirely (the default); set it when diagnosing a slow page.
    db_slow_query_ms: int = Field(default=0, ge=0, le=600000)
    # Delete audit entries older than this many days. 0 keeps them forever (the
    # default); set a positive value to enforce a retention window via the sweep.
    audit_retention_days: int = Field(default=0, ge=0, le=3650)
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
    # A session renews itself while it is being used (POST /auth/session/renew),
    # up to this long after signing in; then the person signs in again.
    auth_session_max_hours: int = 12
    #: How many proxies sit in front of the gateway. Above zero, a request's
    #: address is read from X-Forwarded-For that many hops back; at zero it is
    #: the connecting address and the header is ignored (anyone can forge it).
    trusted_proxy_hops: int = 0
    # OpenTelemetry traces of each request and its database statements, sent
    # over OTLP to OTEL_EXPORTER_OTLP_ENDPOINT (A7). Off by default.
    otel_enabled: bool = False
    otel_service_name: str = "pipewright-gateway"
    # Shown under Help, Contact support: an email address or a web address.
    support_contact: str | None = None
    # "local": files on this machine's disk (upload_root_path). "s3": an
    # S3-compatible bucket (AWS S3, MinIO, R2...), so every gateway and worker
    # reads the same files.
    storage_backend: Literal["local", "s3"] = "local"
    storage_s3_bucket: str | None = None
    # Keys go under this folder in the bucket, so one bucket can hold more.
    storage_s3_prefix: str = ""
    # Empty for AWS; the store's address otherwise (http://minio:9000).
    storage_s3_endpoint_url: str | None = None
    storage_s3_region: str | None = None
    # Empty to use the machine's own AWS credentials (an instance role).
    storage_s3_access_key_id: str | None = None
    storage_s3_secret_access_key: str | None = None
    upload_root_path: str = "data/uploads"
    #: 32 random bytes, base64. When set, every stored file is AES-256-GCM
    #: encrypted at rest; files stored before keep reading until
    #: `platform-encrypt-storage` encrypts them.
    storage_encryption_key: str | None = None
    # Files over 25MB are read by the background worker (A7); it needs about
    # fifteen times a file's size in memory while it reads one.
    max_upload_size_bytes: int = 200 * 1024 * 1024
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
    # Runs one project may have going at once, unless the project sets its own
    # (D2, O8): recipe runs, imports, deliveries and workflow runs. Queued work
    # waits; a run a person starts beyond it is refused with the reason.
    # WORKFLOW_MAX_RUNS_PER_PROJECT is its name from when it counted only
    # workflow runs, and is still read.
    project_runs_at_once: int = Field(
        default=4, ge=1, le=100,
        validation_alias=AliasChoices("PROJECT_RUNS_AT_ONCE", "WORKFLOW_MAX_RUNS_PER_PROJECT"),
    )
    # RUN_MEMORY_LIMIT_MB (default 2048), the most memory one run's data may
    # take, is read where it is enforced: `shared_python.memory` (D2, O8).
    # How long a workflow run whose worker stopped stays "running" before it is
    # failed and can be picked up. A live worker renews it as it goes (A7).
    workflow_lease_seconds: int = Field(default=180, ge=60, le=86400)

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def validate_cors_origins(cls, value):
        return parse_cors_origins(value)

    @field_validator("upload_root_path", mode="after")
    @classmethod
    def anchor_upload_root(cls, value: str) -> str:
        """A relative path is under apps/api-gateway, not wherever a process started.

        The gateway, the worker and the ticker must find the same files; with
        the path left relative to the working directory, `make dev` (started
        in the repository root) and a gateway started in apps/api-gateway
        stored files in two different folders, and scheduled runs reported
        the files missing.
        """
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else _GATEWAY_DIR / path)

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

# Server-folder sources and destinations read SERVER_FILES_ROOT themselves
# (shared_python.server_files). Anchor a relative one the same way, so the
# gateway and the worker confine to the same folder.
_server_files = Path(os.environ.get("SERVER_FILES_ROOT") or "data/server-files").expanduser()
os.environ["SERVER_FILES_ROOT"] = str(_server_files if _server_files.is_absolute() else _GATEWAY_DIR / _server_files)
