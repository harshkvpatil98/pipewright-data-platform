from __future__ import annotations

import time
from typing import Any

import httpx

POWER_BI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"


def _authority_base(config: dict[str, Any]) -> str:
    if config.get("authority_url"):
        return str(config["authority_url"]).rstrip("/")
    tenant = config["tenant_id"]
    return f"https://login.microsoftonline.com/{tenant}"


def fetch_power_bi_access_token(config: dict[str, Any]) -> str:
    base = _authority_base(config)
    token_url = f"{base}/oauth2/v2.0/token"
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "scope": POWER_BI_SCOPE,
        "grant_type": "client_credentials",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(token_url, data=data)
        resp.raise_for_status()
        body = resp.json()
    token = body.get("access_token")
    if not token or not isinstance(token, str):
        raise ValueError("Token response missing access_token.")
    return token


def check_power_bi_connection(config: dict[str, Any]) -> tuple[bool, str, float | None, list[str]]:
    """Client-credentials token + lightweight Power BI REST probe (workspace list)."""
    t0 = time.perf_counter()
    warnings: list[str] = []
    try:
        token = fetch_power_bi_access_token(config)
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=30.0) as client:
            r = client.get("https://api.powerbi.com/v1.0/myorg/groups", headers=headers)
            r.raise_for_status()
        wid = config.get("workspace_id")
        if wid:
            data = r.json()
            groups = data.get("value") if isinstance(data, dict) else None
            if isinstance(groups, list):
                ids = {str(g.get("id")) for g in groups if isinstance(g, dict)}
                if str(wid) not in ids:
                    warnings.append("Configured workspace_id was not found in the accessible workspace list.")
    except httpx.HTTPStatusError:
        return False, "Power BI API or identity endpoint returned an error.", _ms_since(t0), warnings
    except httpx.RequestError:
        return False, "Network error contacting Power BI or Microsoft identity.", _ms_since(t0), warnings
    except ValueError:
        return False, "Power BI authentication failed or returned an unexpected response.", _ms_since(t0), warnings
    return True, "Power BI connection succeeded.", _ms_since(t0), warnings


def discover_power_bi_workspaces(config: dict[str, Any]) -> list[dict[str, str]]:
    token = fetch_power_bi_access_token(config)
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30.0) as client:
        r = client.get("https://api.powerbi.com/v1.0/myorg/groups", headers=headers)
        r.raise_for_status()
        data = r.json()
    out: list[dict[str, str]] = []
    groups = data.get("value") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return out
    for g in groups:
        if not isinstance(g, dict):
            continue
        gid = g.get("id")
        name = g.get("name")
        if gid and name:
            out.append({"id": str(gid), "name": str(name)})
    return out


def _ms_since(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000.0, 2)
