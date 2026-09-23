"""SAML sign-in end to end, minus the identity provider.

There is no Okta or Entra tenant on this machine, so the provider is replaced
by a real RSA key and a real signature: the assertions here are signed the same
way an IdP signs them and verified by the same verifier the product uses. Only
the browser hops are absent. The signing machinery is in `conftest.py`.

What these pin is what the gateway adds on top of `service_enterprise.saml`:
that a sign-in is bound to a request we actually made, that the same assertion
cannot be spent twice, and that the person ends up provisioned by the *same*
code path OIDC uses.
"""

from __future__ import annotations

import base64
import datetime as dt
from collections.abc import Iterator

import pytest
from lxml import etree
from signxml import XMLSigner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model mapping
from api_gateway import saml_flow
from service_auth.models import User
from service_enterprise.models import SamlLoginState
from service_enterprise.saml import SAML_NS
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.errors import BadRequestError, UnauthorizedError


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def started(db: Session, saml_settings, saml_now) -> str:
    """Begin a sign-in and return the request id it remembered."""
    saml_flow.begin_login(db, settings=saml_settings, next_path="/projects", now=saml_now)
    return db.scalars(select(SamlLoginState)).one().request_id


# ---- configuration ----

def test_configured_reflects_the_settings(saml_settings, make_saml_settings) -> None:
    assert saml_flow.configured(saml_settings) is True
    assert saml_flow.configured(make_saml_settings(saml_idp_sso_url=None)) is False


def test_status_separates_implemented_from_available(
    saml_settings, make_saml_settings
) -> None:
    available = saml_flow.status(saml_settings)
    assert available["implemented"] is True
    assert available["supported"] is True

    off = saml_flow.status(make_saml_settings(saml_idp_entity_id=None))
    assert off["implemented"] is True
    assert off["supported"] is False


def test_metadata_is_refused_when_no_provider_is_configured(make_saml_settings) -> None:
    with pytest.raises(BadRequestError):
        saml_flow.metadata(make_saml_settings(saml_sp_entity_id=None))


def test_metadata_names_this_deployment(saml_settings) -> None:
    assert saml_settings.saml_sp_entity_id in saml_flow.metadata(saml_settings)


# ---- starting ----

def test_begin_login_remembers_the_request_and_where_to_return(
    db: Session, saml_settings, saml_now
) -> None:
    url = saml_flow.begin_login(
        db, settings=saml_settings, next_path="/projects", now=saml_now
    )
    assert url.startswith(saml_settings.saml_idp_sso_url)
    row = db.scalars(select(SamlLoginState)).one()
    assert row.next_path == "/projects"
    assert row.expires_at is not None


def test_begin_login_refuses_an_offsite_next_path(
    db: Session, saml_settings, saml_now
) -> None:
    saml_flow.begin_login(
        db, settings=saml_settings, next_path="https://evil.example", now=saml_now
    )
    assert db.scalars(select(SamlLoginState)).one().next_path == "/"


def test_begin_login_is_refused_when_saml_is_off(
    db: Session, make_saml_settings, saml_now
) -> None:
    with pytest.raises(BadRequestError):
        saml_flow.begin_login(
            db, settings=make_saml_settings(saml_idp_x509_cert=None), now=saml_now
        )


def test_expired_requests_are_swept(db: Session, saml_settings, saml_now) -> None:
    saml_flow.begin_login(db, settings=saml_settings, now=saml_now)
    assert saml_flow.sweep_expired_states(db, now=saml_now) == 0
    assert saml_flow.sweep_expired_states(db, now=saml_now + dt.timedelta(hours=1)) == 1
    assert db.scalars(select(SamlLoginState)).all() == []


# ---- completing ----

def test_a_signed_assertion_provisions_the_person_it_describes(
    db: Session, started: str, saml_settings, saml_now, sign_saml_response
) -> None:
    user, next_path = saml_flow.complete_login(
        db,
        settings=saml_settings,
        saml_response=sign_saml_response(started),
        now=saml_now,
    )
    assert user.username == "dana@acme.com"
    assert user.email == "dana@acme.com"
    assert user.display_name == "Dana Scully"
    # The group map is shared with OIDC, so a mapped group grants the same role.
    assert user.role == "admin"
    # Marked directory-managed, so SCIM-lite offboarding may sweep it later.
    assert user.auth_source == "sso"
    assert next_path == "/projects"


def test_the_request_is_spent_so_the_same_assertion_cannot_be_replayed(
    db: Session, started: str, saml_settings, saml_now, sign_saml_response
) -> None:
    response = sign_saml_response(started)
    saml_flow.complete_login(
        db, settings=saml_settings, saml_response=response, now=saml_now
    )
    assert db.scalars(select(SamlLoginState)).all() == []

    with pytest.raises(UnauthorizedError, match="did not start here"):
        saml_flow.complete_login(
            db, settings=saml_settings, saml_response=response, now=saml_now
        )


def test_an_assertion_for_a_request_we_never_made_is_refused(
    db: Session, saml_settings, saml_now, sign_saml_response
) -> None:
    with pytest.raises(UnauthorizedError, match="did not start here"):
        saml_flow.complete_login(
            db,
            settings=saml_settings,
            saml_response=sign_saml_response("_never-issued"),
            now=saml_now,
        )


def test_a_stale_request_is_refused_and_still_consumed(
    db: Session, started: str, saml_settings, saml_now, sign_saml_response
) -> None:
    later = saml_now + dt.timedelta(hours=2)
    with pytest.raises(UnauthorizedError, match="took too long"):
        saml_flow.complete_login(
            db,
            settings=saml_settings,
            saml_response=sign_saml_response(started, now=later),
            now=later,
        )
    # Spent regardless of the outcome: a failed attempt must not leave a live
    # request behind for a second try.
    assert db.scalars(select(SamlLoginState)).all() == []


def test_a_failed_verification_still_consumes_the_request(
    db: Session,
    started: str,
    saml_settings,
    saml_now,
    sign_saml_response,
    make_key_and_cert,
) -> None:
    other_key, other_cert = make_key_and_cert()
    document = etree.fromstring(base64.b64decode(sign_saml_response(started)))
    # Re-sign with a key the deployment does not trust.
    for signature in document.iter("{http://www.w3.org/2000/09/xmldsig#}Signature"):
        signature.getparent().remove(signature)
    assertion = document.find(f"{{{SAML_NS}}}Assertion")
    signed = XMLSigner().sign(assertion, key=other_key, cert=other_cert, id_attribute="ID")
    document.replace(assertion, signed)
    forged = base64.b64encode(etree.tostring(document)).decode()

    with pytest.raises(UnauthorizedError):
        saml_flow.complete_login(
            db, settings=saml_settings, saml_response=forged, now=saml_now
        )
    assert db.scalars(select(SamlLoginState)).all() == []


def test_an_existing_person_is_not_demoted_by_a_saml_sign_in(
    db: Session, saml_settings, saml_now, sign_saml_response
) -> None:
    """The same rule OIDC follows, because it is the same provisioner."""
    db.add(
        User(
            username="dana@acme.com",
            password_hash=hash_password("unused"),
            role="admin",
            is_active=True,
        )
    )
    db.commit()

    saml_flow.begin_login(db, settings=saml_settings, now=saml_now)
    request_id = db.scalars(select(SamlLoginState)).one().request_id
    user, _ = saml_flow.complete_login(
        db,
        settings=saml_settings,
        saml_response=sign_saml_response(request_id, groups=("everyone",)),
        now=saml_now,
    )
    assert user.role == "admin"


def test_jit_off_refuses_an_unknown_person(
    db: Session, make_saml_settings, saml_now, sign_saml_response
) -> None:
    settings = make_saml_settings(oidc_allow_jit=False)
    saml_flow.begin_login(db, settings=settings, now=saml_now)
    request_id = db.scalars(select(SamlLoginState)).one().request_id
    with pytest.raises(UnauthorizedError, match="automatic provisioning is off"):
        saml_flow.complete_login(
            db,
            settings=settings,
            saml_response=sign_saml_response(request_id),
            now=saml_now,
        )


def test_an_inactive_account_cannot_sign_in_through_saml(
    db: Session, saml_settings, saml_now, sign_saml_response
) -> None:
    """Offboarding has to hold on every door, not only the password one."""
    db.add(
        User(
            username="dana@acme.com",
            password_hash=hash_password("unused"),
            role="viewer",
            is_active=False,
            auth_source="sso",
        )
    )
    db.commit()

    saml_flow.begin_login(db, settings=saml_settings, now=saml_now)
    request_id = db.scalars(select(SamlLoginState)).one().request_id
    with pytest.raises(UnauthorizedError, match="inactive"):
        saml_flow.complete_login(
            db,
            settings=saml_settings,
            saml_response=sign_saml_response(request_id),
            now=saml_now,
        )


def test_completing_is_refused_when_saml_is_off(
    db: Session, make_saml_settings, saml_now
) -> None:
    with pytest.raises(BadRequestError):
        saml_flow.complete_login(
            db,
            settings=make_saml_settings(saml_idp_entity_id=None),
            saml_response="anything",
            now=saml_now,
        )
