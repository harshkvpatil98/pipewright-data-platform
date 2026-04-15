from __future__ import annotations

import time
from typing import Any

import httpx


def _base_url(config: dict[str, Any]) -> str:
    return str(config["server_url"]).rstrip("/")


def _credentials_payload(config: dict[str, Any]) -> dict[str, Any]:
    site: dict[str, str] = {}
    if config.get("site_name"):
        site["contentUrl"] = str(config["site_name"])
    else:
        site["contentUrl"] = ""

    if config.get("auth_mode") == "personal_access_token":
        return {
            "credentials": {
                "personalAccessTokenName": config["personal_access_token_name"],
                "personalAccessTokenSecret": config["personal_access_token_secret"],
                "site": site,
            }
        }
    return {
        "credentials": {
            "name": config["username"],
            "password": config["password"],
            "site": site,
        }
    }


def tableau_sign_in(config: dict[str, Any]) -> tuple[str, str]:
    base = _base_url(config)
    ver = config.get("api_version", "3.21")
    url = f"{base}/api/{ver}/auth/signin"
    payload = _credentials_payload(config)
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, json=payload, headers={"Accept": "application/json"})
        r.raise_for_status()
        body = r.json()
    creds = body.get("credentials") if isinstance(body, dict) else None
    if not isinstance(creds, dict):
        raise ValueError("Unexpected sign-in response.")
    token = creds.get("token")
    site = creds.get("site")
    if not token or not isinstance(site, dict):
        raise ValueError("Unexpected sign-in response.")
    site_id = site.get("id")
    if not site_id:
        raise ValueError("Unexpected sign-in response.")
    return str(token), str(site_id)


def check_tableau_connection(config: dict[str, Any]) -> tuple[bool, str, float | None, list[str]]:
    t0 = time.perf_counter()
    warnings: list[str] = []
    try:
        token, site_id = tableau_sign_in(config)
        base = _base_url(config)
        ver = config.get("api_version", "3.21")
        proj_url = f"{base}/api/{ver}/sites/{site_id}/projects"
        headers = {"X-Tableau-Auth": token, "Accept": "application/json"}
        with httpx.Client(timeout=30.0) as client:
            r = client.get(proj_url, headers=headers)
            r.raise_for_status()
    except httpx.HTTPStatusError:
        return False, "Tableau REST API returned an error.", _ms_since(t0), warnings
    except httpx.RequestError:
        return False, "Network error contacting Tableau Server.", _ms_since(t0), warnings
    except ValueError:
        return False, "Tableau authentication failed or returned an unexpected response.", _ms_since(t0), warnings
    return True, "Tableau connection succeeded.", _ms_since(t0), warnings


def discover_tableau_projects(config: dict[str, Any]) -> list[dict[str, str]]:
    token, site_id = tableau_sign_in(config)
    base = _base_url(config)
    ver = config.get("api_version", "3.21")
    proj_url = f"{base}/api/{ver}/sites/{site_id}/projects"
    headers = {"X-Tableau-Auth": token, "Accept": "application/json"}
    with httpx.Client(timeout=30.0) as client:
        r = client.get(proj_url, headers=headers)
        r.raise_for_status()
        data = r.json()
    out: list[dict[str, str]] = []
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        return out
    plist = projects.get("project")
    if plist is None:
        return out
    if isinstance(plist, dict):
        plist = [plist]
    if not isinstance(plist, list):
        return out
    for p in plist:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        name = p.get("name")
        if pid and name:
            out.append({"id": str(pid), "name": str(name)})
    return out


def _ms_since(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000.0, 2)
