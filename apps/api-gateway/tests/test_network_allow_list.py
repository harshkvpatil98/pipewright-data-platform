"""An organisation's network list, through the real HTTP stack (A6, W5).

Sign-in by password, every request on a session, and every request with an
API token are refused from outside the list, with the reason; from inside
they work. Saving a list that leaves out the saver's own address is refused,
since it would sign them out for good.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_gateway.metadata  # noqa: F401
from api_gateway.config import settings
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_auth.models import User
from service_auth.tokens import create_api_token
from service_enterprise.models import Organisation
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.network import address_allowed, client_address, parse_networks, NetworkListError

INSIDE = "10.1.2.3"
OUTSIDE = "203.0.113.9"
PASSWORD = "a-long-enough-password"


@pytest.fixture()
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def _db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")

    db = factory()
    organisation = Organisation(name="Acme", slug="acme", allowed_networks_json=["10.0.0.0/8"])
    db.add(organisation)
    db.flush()
    user = User(username="ann", password_hash=hash_password(PASSWORD), role="admin", is_active=True,
                organisation_id=organisation.id)
    db.add(user)
    db.commit()
    _record, api_token = create_api_token(db, user_id=user.id, name="script", scope="read")
    ids = {"organisation": str(organisation.id), "api_token": api_token}
    db.close()
    yield ids
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


client = TestClient(app)


def _from(address: str, **headers) -> dict[str, str]:
    return {"X-Forwarded-For": address, **headers}


def _sign_in(address: str):
    return client.post("/api/v1/auth/login", json={"username": "ann", "password": PASSWORD}, headers=_from(address))


def test_signing_in_from_outside_is_refused_with_the_reason(world) -> None:
    refused = _sign_in(OUTSIDE)
    assert refused.status_code == 403
    assert "Acme only allows access from its own network" in refused.json()["detail"]
    assert OUTSIDE in refused.json()["detail"]
    assert _sign_in(INSIDE).status_code == 200


def test_a_session_stops_working_outside_the_network(world) -> None:
    token = _sign_in(INSIDE).json()["access_token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=_from(INSIDE, **bearer)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=_from(OUTSIDE, **bearer)).status_code == 403


def test_an_api_token_is_held_to_the_same_list(world) -> None:
    bearer = {"Authorization": f"Bearer {world['api_token']}"}
    assert client.get("/api/v1/auth/me", headers=_from(INSIDE, **bearer)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=_from(OUTSIDE, **bearer)).status_code == 403


def test_a_list_that_would_lock_out_its_saver_is_refused(world) -> None:
    token = _sign_in(INSIDE).json()["access_token"]
    bearer = {"Authorization": f"Bearer {token}"}
    path = f"/api/v1/organisations/{world['organisation']}"
    locked_out = client.patch(path, json={"allowed_networks": ["192.168.0.0/16"]}, headers=_from(INSIDE, **bearer))
    assert locked_out.status_code == 400
    assert "your own address" in locked_out.json()["detail"]
    typo = client.patch(path, json={"allowed_networks": ["10.0.0.0/33"]}, headers=_from(INSIDE, **bearer))
    assert typo.status_code == 400 and "'10.0.0.0/33' is not an address or a range" in typo.json()["detail"]
    widened = client.patch(path, json={"allowed_networks": ["10.0.0.0/8", "203.0.113.0/24"]}, headers=_from(INSIDE, **bearer))
    assert widened.status_code == 200 and widened.json()["allowed_networks"] == ["10.0.0.0/8", "203.0.113.0/24"]
    assert _sign_in(OUTSIDE).status_code == 200
    cleared = client.patch(path, json={"allowed_networks": []}, headers=_from(INSIDE, **bearer))
    assert cleared.status_code == 200 and cleared.json()["allowed_networks"] == []


def test_the_forwarded_header_is_ignored_without_a_trusted_proxy() -> None:
    assert client_address("198.51.100.1", "10.0.0.1", 0) == "198.51.100.1"
    assert client_address("198.51.100.1", "10.0.0.1, 172.16.0.9", 1) == "172.16.0.9"
    assert client_address("198.51.100.1", "10.0.0.1, 172.16.0.9", 2) == "10.0.0.1"


def test_networks_parse_and_match() -> None:
    networks = parse_networks(["10.0.0.0/8", " 2001:db8::/32 ", ""])
    assert address_allowed("10.200.1.1", networks)
    assert address_allowed("2001:db8::1", networks)
    assert not address_allowed("11.0.0.1", networks)
    assert not address_allowed("not-an-address", networks)
    with pytest.raises(NetworkListError):
        parse_networks(["office"])
