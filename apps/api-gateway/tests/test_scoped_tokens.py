"""API tokens limited to projects, that expire, and that the audit log names (Phase 23, X2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_auth.models import ApiToken, User
from service_governance.models import AuditEntry
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'tokens.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def _db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(dependencies, "storage_backend", LocalStorageBackend(str(tmp_path / "storage")))
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with factory() as db:
        db.add(User(username="ann", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
        db.commit()
    person = TestClient(app)
    token = person.post("/api/v1/auth/login", json={"username": "ann", "password": PASSWORD}).json()["access_token"]
    person.headers["Authorization"] = f"Bearer {token}"
    shop = _ok(person.post("/api/v1/projects", json={"name": "Shop"}), 201)["id"]
    farm = _ok(person.post("/api/v1/projects", json={"name": "Farm"}), 201)["id"]
    yield {"person": person, "shop": shop, "farm": farm, "db": factory}
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _token(world, **body) -> TestClient:
    made = _ok(world["person"].post("/api/v1/auth/tokens", json={"name": "Nightly sync", "scope": "write", **body}), 201)
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {made['secret']}"
    client.made = made  # type: ignore[attr-defined]
    return client


def test_a_token_limited_to_a_project_reaches_only_that_project(world) -> None:
    limited = _token(world, project_ids=[world["shop"]], expires_in_days=30)
    read = limited.made["token"]  # type: ignore[attr-defined]
    assert read["project_ids"] == [world["shop"]] and read["expires_at"]
    assert [item["name"] for item in _ok(limited.get("/api/v1/projects"))["items"]] == ["Shop"]
    _ok(limited.get(f"/api/v1/projects/{world['shop']}/datasets"))
    _ok(limited.post(f"/api/v1/projects/{world['shop']}/samples/orders"), 201)
    refused = limited.get(f"/api/v1/projects/{world['farm']}/datasets")
    assert refused.status_code == 403 and "limited to 1 project, and this is another" in refused.text
    # Outside its projects: the catalogues and who it is, nothing that spans or changes other work.
    _ok(limited.get("/api/v1/auth/me"))
    _ok(limited.get("/api/v1/connectors"))
    _ok(limited.get("/api/v1/transformations/tools"))
    for method, path in (("POST", "/api/v1/projects"), ("GET", "/api/v1/runs"), ("GET", "/api/v1/audits"),
                         ("GET", "/api/v1/auth/users")):
        response = limited.request(method, path, json={"name": "Elsewhere"} if method == "POST" else None)
        assert response.status_code == 403 and "it cannot reach" in response.text, (method, path, response.text)


def test_a_limited_token_makes_no_token_wider_than_itself(world) -> None:
    limited = _token(world, project_ids=[world["shop"]])
    wider = limited.post("/api/v1/auth/tokens", json={"name": "Wider", "scope": "read"})
    assert wider.status_code == 403 and "its own projects" in wider.text
    other = limited.post("/api/v1/auth/tokens", json={"name": "Other", "scope": "read", "project_ids": [world["farm"]]})
    assert other.status_code == 403
    narrower = _ok(limited.post("/api/v1/auth/tokens", json={"name": "Narrow", "scope": "read",
                                                            "project_ids": [world["shop"]]}), 201)
    # It sees and revokes only the tokens within its projects, not its maker's others.
    world["person"].post("/api/v1/auth/tokens", json={"name": "Everything", "scope": "read"})
    seen = {item["name"] for item in _ok(limited.get("/api/v1/auth/tokens"))["items"]}
    assert seen == {"Nightly sync", "Narrow"}
    everything = next(item for item in _ok(world["person"].get("/api/v1/auth/tokens"))["items"]
                      if item["name"] == "Everything")
    assert limited.delete(f"/api/v1/auth/tokens/{everything['id']}").status_code == 403
    assert limited.delete(f"/api/v1/auth/tokens/{narrower['token']['id']}").status_code == 204


def test_a_token_cannot_be_limited_to_a_project_its_maker_cannot_reach(world) -> None:
    made = world["person"].post("/api/v1/auth/tokens", json={
        "name": "Stranger", "scope": "read", "project_ids": ["00000000-0000-4000-8000-000000000001"]})
    assert made.status_code == 400 and "cannot reach this project" in made.text
    assert world["person"].post("/api/v1/auth/tokens", json={
        "name": "Forever", "scope": "read", "expires_in_days": 0}).status_code == 422


def test_an_expired_token_is_refused_saying_when(world) -> None:
    limited = _token(world, expires_in_days=1)
    _ok(limited.get("/api/v1/projects"))
    with world["db"]() as db:
        token = db.scalar(select(ApiToken).where(ApiToken.name == "Nightly sync"))
        token.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    refused = limited.get("/api/v1/projects")
    assert refused.status_code == 401 and "This API token expired on" in refused.text


def test_the_audit_log_names_the_token(world) -> None:
    limited = _token(world, project_ids=[world["shop"]])
    prefix = limited.made["token"]["prefix"]  # type: ignore[attr-defined]
    _ok(limited.post(f"/api/v1/projects/{world['shop']}/samples/orders"), 201)
    limited.get(f"/api/v1/projects/{world['farm']}/datasets")
    with world["db"]() as db:
        entries = db.scalars(select(AuditEntry).where(AuditEntry.credential.is_not(None))).all()
    assert entries and all(entry.credential == f"API token “Nightly sync” ({prefix})" for entry in entries)
    rows = _ok(world["person"].get("/api/v1/audits"))["items"]
    assert any(row["credential"] == f"API token “Nightly sync” ({prefix})" for row in rows)
    person_rows = [row for row in rows if row["credential"] is None]
    assert person_rows, "a person's own changes name no token"


def test_a_token_is_held_to_its_owner_s_role_in_a_project(world) -> None:
    """A viewer's write token cannot change a project: before X2 the role check let API tokens by."""
    from service_access.models import ProjectMembership

    with world["db"]() as db:
        db.add(User(username="vic", password_hash=hash_password(PASSWORD), role="user", is_active=True))
        db.commit()
        vic = db.scalar(select(User).where(User.username == "vic"))
        db.add(ProjectMembership(project_id=__import__("uuid").UUID(world["shop"]), user_id=vic.id, role="viewer"))
        db.commit()
    viewer = TestClient(app)
    session = viewer.post("/api/v1/auth/login", json={"username": "vic", "password": PASSWORD}).json()["access_token"]
    viewer.headers["Authorization"] = f"Bearer {session}"
    secret = _ok(viewer.post("/api/v1/auth/tokens", json={"name": "Vic's script", "scope": "write"}), 201)["secret"]
    script = TestClient(app)
    script.headers["Authorization"] = f"Bearer {secret}"
    _ok(script.get(f"/api/v1/projects/{world['shop']}/datasets"))
    refused = script.post(f"/api/v1/projects/{world['shop']}/samples/orders")
    assert refused.status_code == 403
    by_session = viewer.post(f"/api/v1/projects/{world['shop']}/samples/orders")
    assert by_session.status_code == 403 and refused.json()["detail"] == by_session.json()["detail"]
