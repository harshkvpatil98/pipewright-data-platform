"""The access guard, exercised through the real HTTP stack.

Unit-testing the rule table proves the policy is right. This proves the policy
is actually *reached* -- that the dependency is mounted, sees the path
parameters, and refuses the request before any handler runs. A permission
system that is correct but not wired up is worth nothing.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from api_gateway.config import settings
from api_gateway.dependencies import get_db
from api_gateway.main import app
from shared_python.auth.security import create_access_token

PROJECT_ID = uuid.UUID("aaaaaaaa-1111-2222-3333-444444444444")
USER_ID = uuid.UUID("bbbbbbbb-1111-2222-3333-444444444444")

client = TestClient(app)


class _StubSession:
    """Enough of a session for the guard; no route gets far enough to need more."""

    def get(self, *_args, **_kwargs):
        return None

    def scalar(self, *_args, **_kwargs):
        return None

    def close(self):
        return None


@pytest.fixture(autouse=True)
def stub_db():
    app.dependency_overrides[get_db] = lambda: _StubSession()
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def token() -> str:
    value, _expires = create_access_token(
        user_id=str(USER_ID),
        username="member",
        secret_key=settings.auth_jwt_secret,
        issuer=settings.auth_jwt_issuer,
        audience=settings.auth_jwt_audience,
        expires_minutes=60,
    )
    return value


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _as_role(monkeypatch: pytest.MonkeyPatch, role: str | None) -> None:
    import service_access.guard as guard_module

    monkeypatch.setattr(guard_module, "role_for", lambda *_a, **_k: role)


def test_a_viewer_is_refused_a_write(monkeypatch: pytest.MonkeyPatch, token: str):
    _as_role(monkeypatch, "viewer")
    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/workflows",
        json={"name": "nightly", "nodes": [], "edges": []},
        headers=_headers(token),
    )
    assert response.status_code == 403
    assert "editor role or above" in response.json()["detail"]


def test_a_viewer_may_still_read(monkeypatch: pytest.MonkeyPatch, token: str):
    _as_role(monkeypatch, "viewer")
    response = client.get(f"/api/v1/projects/{PROJECT_ID}/workflows", headers=_headers(token))
    # The guard lets it through; whatever the handler then decides is its own business.
    assert response.status_code != 403


def test_an_operator_may_run_but_not_define(monkeypatch: pytest.MonkeyPatch, token: str):
    _as_role(monkeypatch, "operator")
    denied = client.post(
        f"/api/v1/projects/{PROJECT_ID}/workflows",
        json={"name": "nightly", "nodes": [], "edges": []},
        headers=_headers(token),
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"/api/v1/projects/{PROJECT_ID}/workflows/{uuid.uuid4()}/run",
        json={"parameters": {}},
        headers=_headers(token),
    )
    assert allowed.status_code != 403


def test_an_editor_may_not_manage_members(monkeypatch: pytest.MonkeyPatch, token: str):
    _as_role(monkeypatch, "editor")
    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/members",
        json={"username": "someone", "role": "viewer"},
        headers=_headers(token),
    )
    assert response.status_code == 403
    assert "admin role or above" in response.json()["detail"]


def test_an_admin_passes_the_guard(monkeypatch: pytest.MonkeyPatch, token: str):
    _as_role(monkeypatch, "admin")
    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/members",
        json={"username": "someone", "role": "viewer"},
        headers=_headers(token),
    )
    assert response.status_code != 403


def test_a_non_member_is_not_told_the_project_exists(monkeypatch: pytest.MonkeyPatch, token: str):
    """No access must read as 404 from the handler, not 403 from the guard."""
    _as_role(monkeypatch, None)
    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/workflows",
        json={"name": "nightly", "nodes": [], "edges": []},
        headers=_headers(token),
    )
    assert response.status_code != 403


def test_the_guard_never_forces_authentication_on_login():
    """Mounting the guard globally must not put a login behind a login."""
    response = client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "wrong-password"}
    )
    assert response.status_code in (401, 422)


def test_an_unauthenticated_project_request_is_a_401_not_a_403():
    response = client.get(f"/api/v1/projects/{PROJECT_ID}/workflows")
    assert response.status_code == 401


def test_a_malformed_token_falls_through_to_the_auth_layer():
    response = client.get(
        f"/api/v1/projects/{PROJECT_ID}/workflows", headers={"Authorization": "Bearer nonsense"}
    )
    assert response.status_code == 401


def test_routes_without_a_project_are_untouched(monkeypatch: pytest.MonkeyPatch, token: str):
    _as_role(monkeypatch, "viewer")
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
