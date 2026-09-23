"""The SAML HTTP surface: status, metadata, start, and the consumer service.

`test_saml_flow.py` pins the logic; this pins the routes a browser and an
identity provider actually touch, including the two things only the route layer
decides -- that a successful assertion sets the same session cookie the password
flow sets, and that a failed one lands the person back on the login screen with
a readable message instead of a JSON stack trace.

The organisation session policy is exercised here too, because the route layer
is where it could most easily be forgotten: the token's lifetime is the visible
proof that the policy reached it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import api_gateway.metadata  # noqa: F401  - registers every service's tables
import service_enterprise  # noqa: F401  - registers the session-policy resolver
from api_gateway import sso_router
from service_auth.models import User
from service_enterprise.models import Organisation, SamlLoginState
from shared_python.auth.security import hash_password
from shared_python.db import Base


@pytest.fixture()
def db() -> Iterator[Session]:
    # TestClient runs the app on its own thread, and the default SQLite pool
    # would hand that thread a second, empty in-memory database.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db: Session, saml_settings) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(sso_router.build_router(lambda: db, saml_settings))
    # Redirects are the thing under test, so they are inspected, not followed.
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


@pytest.fixture()
def assertion_for(sign_saml_response):
    """A response valid *now*.

    The routes read the clock themselves -- that is part of what is being
    tested -- so these assertions are minted against the real one rather than
    the fixed instant the logic tests use.
    """

    def make(request_id: str, **kwargs) -> str:
        return sign_saml_response(request_id, now=dt.datetime.now(dt.UTC), **kwargs)

    return make


def _start(client: TestClient, db: Session, saml_settings, next_path="/projects") -> str:
    response = client.get("/auth/saml/start", params={"next": next_path})
    assert response.status_code == 302
    assert response.headers["location"].startswith(saml_settings.saml_idp_sso_url)
    return db.scalars(select(SamlLoginState)).one().request_id


def _login_error(response, saml_settings) -> str:
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"{saml_settings.web_base_url}/login?sso_error=")
    return location


def _claims(response, saml_settings) -> dict:
    token = response.cookies.get(sso_router.ACCESS_TOKEN_COOKIE)
    assert token, "the sign-in did not set a session cookie"
    return jwt.decode(
        token,
        saml_settings.auth_jwt_secret,
        algorithms=["HS256"],
        issuer=saml_settings.auth_jwt_issuer,
        audience=saml_settings.auth_jwt_audience,
    )


def _lifetime(claims: dict) -> dt.timedelta:
    return dt.datetime.fromtimestamp(claims["exp"], dt.UTC) - dt.datetime.now(dt.UTC)


# ---- status and metadata ----

def test_status_tells_the_login_screen_what_is_on_offer(client: TestClient) -> None:
    body = client.get("/auth/sso/status").json()
    assert body["saml_configured"] is True
    assert body["saml"]["implemented"] is True
    assert body["saml"]["supported"] is True
    # OIDC is unset in these settings, and the status says so rather than
    # implying that "SSO" is one thing.
    assert body["oidc_configured"] is False


def test_metadata_is_served_as_saml_metadata(client: TestClient) -> None:
    response = client.get("/auth/saml/metadata")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/samlmetadata+xml")
    assert 'WantAssertionsSigned="true"' in response.text


# ---- the round trip ----

def test_a_valid_assertion_signs_the_person_in_and_sets_the_session_cookie(
    client: TestClient, db: Session, saml_settings, assertion_for
) -> None:
    request_id = _start(client, db, saml_settings)
    response = client.post(
        "/auth/saml/acs", data={"SAMLResponse": assertion_for(request_id)}
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"{saml_settings.web_base_url}/projects"
    assert _claims(response, saml_settings)["username"] == "dana@acme.com"

    user = db.scalars(select(User).where(User.username == "dana@acme.com")).one()
    assert user.role == "admin"


def test_an_empty_assertion_returns_the_person_to_the_login_screen(
    client: TestClient, saml_settings
) -> None:
    _login_error(client.post("/auth/saml/acs", data={"SAMLResponse": ""}), saml_settings)


def test_a_forged_assertion_returns_a_readable_message_not_a_stack_trace(
    client: TestClient, db: Session, saml_settings
) -> None:
    _start(client, db, saml_settings)
    location = _login_error(
        client.post("/auth/saml/acs", data={"SAMLResponse": "bm90LXhtbA=="}),
        saml_settings,
    )
    assert "sso_error" in location
    # Nothing was created by a failed sign-in.
    assert db.scalars(select(User)).all() == []


def test_replaying_a_spent_assertion_is_refused_at_the_route(
    client: TestClient, db: Session, saml_settings, assertion_for
) -> None:
    request_id = _start(client, db, saml_settings)
    response = assertion_for(request_id)
    assert client.post("/auth/saml/acs", data={"SAMLResponse": response}).status_code == 303
    _login_error(
        client.post("/auth/saml/acs", data={"SAMLResponse": response}), saml_settings
    )


def test_start_is_refused_when_saml_is_not_configured(
    db: Session, make_saml_settings
) -> None:
    settings = make_saml_settings(saml_idp_sso_url=None)
    app = FastAPI()
    app.include_router(sso_router.build_router(lambda: db, settings))
    with TestClient(app, follow_redirects=False) as unconfigured:
        _login_error(unconfigured.get("/auth/saml/start"), settings)
        assert unconfigured.get("/auth/saml/metadata").status_code == 404


# ---- the organisation's session policy, visible in the token ----

def test_the_organisations_session_policy_shortens_the_saml_session(
    client: TestClient, db: Session, saml_settings, assertion_for
) -> None:
    organisation = Organisation(
        name="Acme", slug="acme", plan="standard", session_max_minutes=15
    )
    db.add(organisation)
    db.flush()
    db.add(
        User(
            username="dana@acme.com",
            password_hash=hash_password("unused"),
            role="viewer",
            is_active=True,
            auth_source="sso",
            organisation_id=organisation.id,
        )
    )
    db.commit()

    request_id = _start(client, db, saml_settings)
    response = client.post(
        "/auth/saml/acs", data={"SAMLResponse": assertion_for(request_id)}
    )
    assert response.status_code == 303
    # 15 minutes from the tenant's policy, not the deployment's 60.
    lifetime = _lifetime(_claims(response, saml_settings))
    assert dt.timedelta(minutes=13) < lifetime <= dt.timedelta(minutes=15)


def test_without_an_organisation_the_deployment_default_still_applies(
    client: TestClient, db: Session, saml_settings, assertion_for
) -> None:
    request_id = _start(client, db, saml_settings)
    response = client.post(
        "/auth/saml/acs", data={"SAMLResponse": assertion_for(request_id)}
    )
    lifetime = _lifetime(_claims(response, saml_settings))
    assert dt.timedelta(minutes=58) < lifetime <= dt.timedelta(minutes=60)
