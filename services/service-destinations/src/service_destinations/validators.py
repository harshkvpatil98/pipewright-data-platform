from __future__ import annotations

import re
import uuid
from typing import Any

from shared_python.errors import BadRequestError
from shared_python.security.encryption import STORED_SECRET_PREFIX

DESTINATION_TYPES = frozenset({"postgres", "s3", "local_export"})
BI_INTEGRATION_TYPES = frozenset({"power_bi", "tableau"})
STATUS_VALUES = frozenset({"active", "disabled"})

def _is_stored_cipher(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(STORED_SECRET_PREFIX)


_SECRET_KEYS = frozenset(
    {
        "password",
        "secret_access_key",
        "aws_secret_access_key",
        "secret",
    }
)


def is_secret_key(key: str) -> bool:
    kl = key.lower()
    if kl in _SECRET_KEYS:
        return True
    return "secret" in kl or kl.endswith("_token") or kl == "passwd"


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe for API responses (passwords and secrets masked)."""
    out: dict[str, Any] = {}
    for key, value in config.items():
        if is_secret_key(key):
            out[key] = "***"
        elif isinstance(value, dict):
            out[key] = redact_config(value)
        else:
            out[key] = value
    return out


def merge_config_preserving_secrets(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    *,
    destination_type: str,
) -> dict[str, Any]:
    """PATCH merge: placeholder '***' or missing secret keys keep stored values."""
    merged = {**existing, **incoming}
    if destination_type == "postgres":
        pw = incoming.get("password")
        if pw in (None, "", "***"):
            merged["password"] = existing.get("password", "")
    elif destination_type == "s3":
        sk = incoming.get("secret_access_key")
        if sk in (None, "", "***"):
            merged["secret_access_key"] = existing.get("secret_access_key", "")
    elif destination_type == "power_bi":
        cs = incoming.get("client_secret")
        if cs in (None, "", "***"):
            merged["client_secret"] = existing.get("client_secret", "")
    elif destination_type == "tableau":
        pw = incoming.get("password")
        if pw in (None, "", "***"):
            merged["password"] = existing.get("password", "")
        pts = incoming.get("personal_access_token_secret")
        if pts in (None, "", "***"):
            merged["personal_access_token_secret"] = existing.get("personal_access_token_secret", "")
    return merged


def _non_empty_str(value: Any, field: str) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise BadRequestError(f'"{field}" is required for this destination type.')
    if not isinstance(value, str):
        raise BadRequestError(f'"{field}" must be a string.')
    return value.strip()


def validate_postgres_config(raw: dict[str, Any]) -> dict[str, Any]:
    host = _non_empty_str(raw.get("host"), "host")
    database = _non_empty_str(raw.get("database"), "database")
    username = _non_empty_str(raw.get("username"), "username")
    password = raw.get("password")
    if _is_stored_cipher(password):
        pass
    elif password is None or (isinstance(password, str) and not password):
        raise BadRequestError('"password" is required when creating a PostgreSQL destination.')
    elif not isinstance(password, str):
        raise BadRequestError('"password" must be a string.')

    port_raw = raw.get("port", 5432)
    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise BadRequestError('"port" must be an integer between 1 and 65535.') from exc
    if port < 1 or port > 65535:
        raise BadRequestError('"port" must be between 1 and 65535.')

    ssl_mode = raw.get("ssl_mode")
    if ssl_mode is not None:
        if not isinstance(ssl_mode, str):
            raise BadRequestError('"ssl_mode" must be a string.')
        allowed = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
        if ssl_mode not in allowed:
            raise BadRequestError(f'"ssl_mode" must be one of: {", ".join(sorted(allowed))}.')

    schema_name = raw.get("schema") or raw.get("db_schema")
    if schema_name is not None and (not isinstance(schema_name, str) or not schema_name.strip()):
        raise BadRequestError('"schema" must be a non-empty string when provided.')
    if schema_name is not None and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", schema_name.strip()):
        raise BadRequestError('"schema" must be a valid PostgreSQL identifier.')

    out: dict[str, Any] = {
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "password": password,
    }
    if schema_name is not None:
        out["schema"] = schema_name.strip()
    if ssl_mode is not None:
        out["ssl_mode"] = ssl_mode.strip()
    return out


def validate_s3_config(raw: dict[str, Any]) -> dict[str, Any]:
    bucket = _non_empty_str(raw.get("bucket"), "bucket")
    access_key_id = _non_empty_str(raw.get("access_key_id"), "access_key_id")
    secret = raw.get("secret_access_key")
    if _is_stored_cipher(secret):
        pass
    elif secret is None or (isinstance(secret, str) and not secret):
        raise BadRequestError('"secret_access_key" is required for an S3 destination.')
    elif not isinstance(secret, str):
        raise BadRequestError('"secret_access_key" must be a string.')

    region = raw.get("region")
    if region is not None:
        if not isinstance(region, str) or not region.strip():
            raise BadRequestError('"region" must be a non-empty string when provided.')
        region = region.strip()

    prefix = raw.get("prefix")
    if prefix is not None:
        if not isinstance(prefix, str):
            raise BadRequestError('"prefix" must be a string.')
        prefix = prefix.strip() or ""

    out: dict[str, Any] = {
        "bucket": bucket,
        "access_key_id": access_key_id,
        "secret_access_key": secret,
    }
    if region is not None:
        out["region"] = region
    if prefix is not None:
        out["prefix"] = prefix
    return out


def validate_local_export_config(raw: dict[str, Any]) -> dict[str, Any]:
    path = _non_empty_str(raw.get("path"), "path")
    return {"path": path}


def validate_power_bi_config(raw: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _non_empty_str(raw.get("tenant_id"), "tenant_id")
    client_id = _non_empty_str(raw.get("client_id"), "client_id")
    client_secret = raw.get("client_secret")
    if _is_stored_cipher(client_secret):
        pass
    elif client_secret is None or (isinstance(client_secret, str) and not client_secret):
        raise BadRequestError('"client_secret" is required when creating a Power BI connection.')
    elif not isinstance(client_secret, str):
        raise BadRequestError('"client_secret" must be a string.')

    authority_url = raw.get("authority_url")
    if authority_url is not None:
        if not isinstance(authority_url, str) or not authority_url.strip():
            raise BadRequestError('"authority_url" must be a non-empty string when provided.')
        authority_url = authority_url.strip().rstrip("/")
        if not authority_url.lower().startswith("https://"):
            raise BadRequestError('"authority_url" must be an https URL.')

    workspace_id = raw.get("workspace_id")
    if workspace_id is not None:
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise BadRequestError('"workspace_id" must be a non-empty string when provided.')
        try:
            uuid.UUID(workspace_id.strip())
        except ValueError as exc:
            raise BadRequestError('"workspace_id" must be a valid UUID.') from exc
        workspace_id = workspace_id.strip()

    out: dict[str, Any] = {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if authority_url is not None:
        out["authority_url"] = authority_url
    if workspace_id is not None:
        out["workspace_id"] = workspace_id
    return out


def validate_tableau_config(raw: dict[str, Any]) -> dict[str, Any]:
    server_url = _non_empty_str(raw.get("server_url"), "server_url")
    server_url = server_url.strip().rstrip("/")
    if not server_url.lower().startswith("https://"):
        raise BadRequestError('"server_url" must be an https URL.')

    auth_mode = raw.get("auth_mode", "password")
    if not isinstance(auth_mode, str) or auth_mode not in ("password", "personal_access_token"):
        raise BadRequestError('"auth_mode" must be "password" or "personal_access_token".')

    api_version = raw.get("api_version", "3.21")
    if not isinstance(api_version, str) or not re.match(r"^\d+\.\d+$", api_version.strip()):
        raise BadRequestError('"api_version" must look like a Tableau REST version (e.g. "3.21").')
    api_version = api_version.strip()

    site_name = raw.get("site_name")
    if site_name is not None:
        if not isinstance(site_name, str):
            raise BadRequestError('"site_name" must be a string.')
        site_name = site_name.strip()

    username: str | None = None
    password: str | None = None
    pat_name: str | None = None
    pat_secret: str | None = None

    if auth_mode == "password":
        username = _non_empty_str(raw.get("username"), "username")
        password = raw.get("password")
        if _is_stored_cipher(password):
            pass
        elif password is None or (isinstance(password, str) and not password):
            raise BadRequestError('"password" is required for password auth_mode.')
        elif not isinstance(password, str):
            raise BadRequestError('"password" must be a string.')
    else:
        pat_name = _non_empty_str(raw.get("personal_access_token_name"), "personal_access_token_name")
        pat_secret = raw.get("personal_access_token_secret")
        if _is_stored_cipher(pat_secret):
            pass
        elif pat_secret is None or (isinstance(pat_secret, str) and not pat_secret):
            raise BadRequestError(
                '"personal_access_token_secret" is required for personal_access_token auth_mode.'
            )
        elif not isinstance(pat_secret, str):
            raise BadRequestError('"personal_access_token_secret" must be a string.')

    out: dict[str, Any] = {
        "server_url": server_url,
        "auth_mode": auth_mode,
        "api_version": api_version,
    }
    if site_name is not None:
        out["site_name"] = site_name
    if username is not None:
        out["username"] = username
    if password is not None:
        out["password"] = password
    if pat_name is not None:
        out["personal_access_token_name"] = pat_name
    if pat_secret is not None:
        out["personal_access_token_secret"] = pat_secret
    return out


def validate_config_for_type(destination_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    if destination_type == "postgres":
        return validate_postgres_config(raw)
    if destination_type == "s3":
        return validate_s3_config(raw)
    if destination_type == "local_export":
        return validate_local_export_config(raw)
    if destination_type == "power_bi":
        return validate_power_bi_config(raw)
    if destination_type == "tableau":
        return validate_tableau_config(raw)
    raise BadRequestError("Unsupported destination type.")
