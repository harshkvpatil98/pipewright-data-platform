"""Sign-in and shared dashboards are rate limited, through the HTTP stack (A7, X5)."""

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
from shared_python import rate_limit
from shared_python.auth.security import hash_password
from shared_python.db import Base

PASSWORD = "a-long-enough-password"


@pytest.fixture()
def client(monkeypatch):
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
    db.add(User(username="ann", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
    db.commit()
    db.close()
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _sign_in(client, password: str, address: str = "198.51.100.7"):
    return client.post(
        "/api/v1/auth/login", json={"username": "ann", "password": password}, headers={"X-Forwarded-For": address}
    )


def test_guessing_a_password_is_stopped_with_when_to_try_again(client) -> None:
    for _ in range(rate_limit.SIGN_IN_PER_ACCOUNT.count):
        assert _sign_in(client, "wrong-password-guess").status_code == 401
    refused = _sign_in(client, PASSWORD)  # even the right one, until the window ends
    assert refused.status_code == 429
    assert refused.json()["detail"].startswith("Too many sign-in attempts for this account. Try again in")
    assert 0 < int(refused.headers["Retry-After"]) <= rate_limit.SIGN_IN_PER_ACCOUNT.seconds
    # The account is not locked for everyone: the limit is per account and address.
    assert _sign_in(client, PASSWORD, address="203.0.113.50").status_code == 200


def test_a_shared_dashboard_link_cannot_be_hammered(client, monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, "PUBLIC_DASHBOARD_PER_ADDRESS", rate_limit.Limit("public-dashboard", 2, 60, "requests for shared dashboards from this address"))
    answers = [client.get("/api/v1/public/dashboards/not-a-real-token").status_code for _ in range(3)]
    assert answers == [404, 404, 429]
