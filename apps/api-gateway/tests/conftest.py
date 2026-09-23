"""Shared machinery for the SAML tests.

Signing an assertion takes an RSA key, a certificate and a page of XML, and two
test modules need the same ones. It lives here rather than in either of them
because the suite runs with `--import-mode=importlib` (see `scripts/test.sh`),
so test modules cannot import each other -- fixtures are the supported way to
share, and a session-scoped key means the whole file pays for one keygen
instead of one per test.
"""

from __future__ import annotations

import base64
import datetime as dt
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLSigner

from service_enterprise.saml import SAML_NS

IDP_ENTITY_ID = "https://idp.example.com/metadata"
IDP_SSO_URL = "https://idp.example.com/sso/saml"
SP_ENTITY_ID = "https://app.example.com/saml"
ACS_URL = "https://app.example.com/api/v1/auth/saml/acs"
WEB_BASE_URL = "https://app.example.com"
# A fixed instant, so an assertion's validity window is a property of the test
# rather than of when it happened to run.
SAML_NOW = dt.datetime(2026, 9, 23, 10, 0, tzinfo=dt.UTC)


def _instant(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_key_and_cert() -> tuple[str, str]:
    """An RSA key and a self-signed certificate, standing in for an IdP's."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.example.com")])
    anchor = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(anchor)
        .not_valid_after(anchor + dt.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    return (
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        certificate.public_bytes(serialization.Encoding.PEM).decode(),
    )


@pytest.fixture(scope="session")
def make_key_and_cert() -> Callable[[], tuple[str, str]]:
    """For the tests that need a *second*, untrusted key pair."""
    return _make_key_and_cert


@pytest.fixture(scope="session")
def saml_credentials() -> tuple[str, str]:
    return _make_key_and_cert()


@pytest.fixture(scope="session")
def saml_now() -> dt.datetime:
    return SAML_NOW


@pytest.fixture(scope="session")
def make_saml_settings(saml_credentials) -> Callable[..., SimpleNamespace]:
    _key, certificate = saml_credentials

    def make(**overrides) -> SimpleNamespace:
        base = dict(
            saml_idp_entity_id=IDP_ENTITY_ID,
            saml_idp_sso_url=IDP_SSO_URL,
            saml_idp_x509_cert=certificate,
            saml_sp_entity_id=SP_ENTITY_ID,
            saml_sp_acs_url=ACS_URL,
            saml_group_role_map='{"data-admins": "admin"}',
            # OIDC is deliberately unset: these settings describe a deployment
            # that speaks SAML only, which is the case SAML exists for.
            oidc_issuer=None,
            oidc_client_id=None,
            oidc_client_secret=None,
            oidc_redirect_uri=None,
            oidc_default_role="viewer",
            oidc_allow_jit=True,
            auth_jwt_secret="x" * 40,
            auth_jwt_issuer="pipewright",
            auth_jwt_audience="pipewright-web",
            auth_access_token_exp_minutes=60,
            web_base_url=WEB_BASE_URL,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    return make


@pytest.fixture()
def saml_settings(make_saml_settings) -> SimpleNamespace:
    return make_saml_settings()


def _response_xml(
    request_id: str,
    *,
    name_id: str,
    groups: tuple[str, ...],
    display_name: str,
    now: dt.datetime,
) -> str:
    values = "".join(f"<saml:AttributeValue>{g}</saml:AttributeValue>" for g in groups)
    return (
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="_resp1" Version="2.0" IssueInstant="{_instant(now)}" '
        f'Destination="{ACS_URL}" InResponseTo="{request_id}">'
        f"<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>"
        '<samlp:Status><samlp:StatusCode '
        'Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        f'<saml:Assertion ID="_a1" Version="2.0" IssueInstant="{_instant(now)}">'
        f"<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>"
        "<saml:Subject>"
        '<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">'
        f"{name_id}</saml:NameID>"
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{_instant(now + dt.timedelta(minutes=5))}" '
        f'Recipient="{ACS_URL}" InResponseTo="{request_id}"/>'
        "</saml:SubjectConfirmation></saml:Subject>"
        f'<saml:Conditions NotBefore="{_instant(now - dt.timedelta(minutes=1))}" '
        f'NotOnOrAfter="{_instant(now + dt.timedelta(minutes=5))}">'
        f"<saml:AudienceRestriction><saml:Audience>{SP_ENTITY_ID}</saml:Audience>"
        "</saml:AudienceRestriction></saml:Conditions>"
        "<saml:AttributeStatement>"
        f'<saml:Attribute Name="groups">{values}</saml:Attribute>'
        '<saml:Attribute Name="displayName">'
        f"<saml:AttributeValue>{display_name}</saml:AttributeValue></saml:Attribute>"
        "</saml:AttributeStatement>"
        "</saml:Assertion></samlp:Response>"
    )


def sign_assertion(xml: str, *, key_pem: str, cert_pem: str) -> str:
    """Sign the response's assertion in place, the way Okta and Entra do."""
    document = etree.fromstring(xml.encode())
    assertion = document.find(f"{{{SAML_NS}}}Assertion")
    signed = XMLSigner().sign(assertion, key=key_pem, cert=cert_pem, id_attribute="ID")
    document.replace(assertion, signed)
    return base64.b64encode(etree.tostring(document)).decode()


@pytest.fixture(scope="session")
def sign_saml_response(saml_credentials) -> Callable[..., str]:
    """A base64 SAMLResponse carrying one genuinely signed assertion."""
    key, certificate = saml_credentials

    def make(
        request_id: str,
        *,
        name_id: str = "dana@acme.com",
        groups: tuple[str, ...] = ("data-admins",),
        display_name: str = "Dana Scully",
        now: dt.datetime = SAML_NOW,
    ) -> str:
        xml = _response_xml(
            request_id,
            name_id=name_id,
            groups=groups,
            display_name=display_name,
            now=now,
        )
        return sign_assertion(xml, key_pem=key, cert_pem=certificate)

    return make
