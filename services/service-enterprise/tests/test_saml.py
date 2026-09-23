"""SAML: a real signature, and every way a bad assertion must be refused.

The signatures here are genuine. Each test mints an RSA key and a self-signed
certificate, signs an assertion with it, and hands the result to the same
verifier the product uses -- so "the signature is checked" is demonstrated
rather than asserted. What is faked is only the transport: there is no live
Okta or Entra tenant on this machine, so the assertions are built to the shapes
those two providers emit rather than captured from them.

The rejection tests matter more than the acceptance test. Every one of them is
a way into somebody's account if the check it pins were ever removed.
"""

from __future__ import annotations

import base64
import datetime as dt

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLSigner

from service_enterprise.saml import (
    SAML_NS,
    SamlConfig,
    build_authn_request,
    claims_from_attributes,
    config_from_settings,
    decode_response,
    is_configured,
    normalise_certificate,
    saml_status,
    sp_metadata_xml,
    unverified_in_response_to,
    verify_response,
)
from service_enterprise.sso import map_identity
from shared_python.errors import BadRequestError, UnauthorizedError

IDP_ENTITY_ID = "https://idp.example.com/metadata"
IDP_SSO_URL = "https://idp.example.com/sso/saml"
SP_ENTITY_ID = "https://app.example.com/saml"
ACS_URL = "https://app.example.com/api/v1/auth/saml/acs"
REQUEST_ID = "_req0123456789"
NOW = dt.datetime(2026, 9, 23, 10, 0, tzinfo=dt.UTC)


def _make_key_and_cert() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.example.com")])
    anchor = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    cert = (
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
        cert.public_bytes(serialization.Encoding.PEM).decode(),
    )


# One key pair for the whole module: generating RSA keys is slow, and only the
# tests that need a *second*, wrong key pay for one.
KEY_PEM, CERT_PEM = _make_key_and_cert()


def _config(**overrides) -> SamlConfig:
    base = dict(
        idp_entity_id=IDP_ENTITY_ID,
        idp_sso_url=IDP_SSO_URL,
        idp_x509_cert=CERT_PEM,
        sp_entity_id=SP_ENTITY_ID,
        sp_acs_url=ACS_URL,
        group_role_map={"data-admins": "admin"},
        default_role="viewer",
    )
    base.update(overrides)
    return SamlConfig(**base)


def _instant(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _response_xml(
    *,
    issuer: str = IDP_ENTITY_ID,
    audience: str = SP_ENTITY_ID,
    recipient: str = ACS_URL,
    destination: str | None = ACS_URL,
    in_response_to: str | None = REQUEST_ID,
    subject_in_response_to: str | None = REQUEST_ID,
    name_id: str = "dana@acme.com",
    name_id_format: str = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
    not_before: dt.datetime | None = None,
    not_on_or_after: dt.datetime | None = None,
    status_code: str = "urn:oasis:names:tc:SAML:2.0:status:Success",
    attributes: str = (
        '<saml:AttributeStatement>'
        '<saml:Attribute Name="groups">'
        "<saml:AttributeValue>data-admins</saml:AttributeValue>"
        "<saml:AttributeValue>everyone</saml:AttributeValue>"
        "</saml:Attribute>"
        '<saml:Attribute Name="displayName">'
        "<saml:AttributeValue>Dana Scully</saml:AttributeValue>"
        "</saml:Attribute>"
        "</saml:AttributeStatement>"
    ),
    conditions: str | None = None,
    assertion_count: int = 1,
) -> str:
    not_before = not_before or (NOW - dt.timedelta(minutes=1))
    not_on_or_after = not_on_or_after or (NOW + dt.timedelta(minutes=5))
    if conditions is None:
        conditions = (
            f'<saml:Conditions NotBefore="{_instant(not_before)}" '
            f'NotOnOrAfter="{_instant(not_on_or_after)}">'
            f"<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience>"
            "</saml:AudienceRestriction></saml:Conditions>"
        )
    subject_irt = (
        f' InResponseTo="{subject_in_response_to}"' if subject_in_response_to else ""
    )
    assertion = (
        f'<saml:Assertion ID="_a{{index}}" Version="2.0" '
        f'IssueInstant="{_instant(NOW)}">'
        f"<saml:Issuer>{issuer}</saml:Issuer>"
        "<saml:Subject>"
        f'<saml:NameID Format="{name_id_format}">{name_id}</saml:NameID>'
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{_instant(not_on_or_after)}" '
        f'Recipient="{recipient}"{subject_irt}/>'
        "</saml:SubjectConfirmation></saml:Subject>"
        f"{conditions}{attributes}</saml:Assertion>"
    )
    assertions = "".join(assertion.format(index=i) for i in range(assertion_count))
    irt = f' InResponseTo="{in_response_to}"' if in_response_to else ""
    dest = f' Destination="{destination}"' if destination else ""
    return (
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="_resp1" Version="2.0" IssueInstant="{_instant(NOW)}"{dest}{irt}>'
        f"<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>"
        f'<samlp:Status><samlp:StatusCode Value="{status_code}"/></samlp:Status>'
        f"{assertions}</samlp:Response>"
    )


def _sign(xml: str, *, key_pem: str = KEY_PEM, cert_pem: str = CERT_PEM, which: int = 0) -> str:
    """Sign the assertion in place, the way Okta and Entra do by default."""
    document = etree.fromstring(xml.encode())
    assertions = document.findall(f"{{{SAML_NS}}}Assertion")
    target = assertions[which]
    signed = XMLSigner().sign(target, key=key_pem, cert=cert_pem, id_attribute="ID")
    document.replace(target, signed)
    return base64.b64encode(etree.tostring(document)).decode()


def _verify(encoded: str, *, config: SamlConfig | None = None, now: dt.datetime = NOW):
    return verify_response(
        encoded,
        config=config or _config(),
        expected_request_id=REQUEST_ID,
        now=now,
    )


# ---- the request we send ----------------------------------------------------

def test_authn_request_is_a_deflated_redirect_carrying_our_entity_id():
    request = build_authn_request(_config(), now=NOW)
    assert request.url.startswith(IDP_SSO_URL + "?SAMLRequest=")
    # A SAML ID is an xsd:ID and may not begin with a digit.
    assert request.request_id.startswith("_")

    from urllib.parse import parse_qs, urlparse
    import zlib

    encoded = parse_qs(urlparse(request.url).query)["SAMLRequest"][0]
    xml = zlib.decompress(base64.b64decode(encoded), -15).decode()
    assert f'ID="{request.request_id}"' in xml
    assert f"<saml:Issuer>{SP_ENTITY_ID}</saml:Issuer>" in xml
    assert f'AssertionConsumerServiceURL="{ACS_URL}"' in xml


def test_two_requests_never_share_an_id():
    first = build_authn_request(_config(), now=NOW)
    second = build_authn_request(_config(), now=NOW)
    assert first.request_id != second.request_id


def test_unconfigured_saml_refuses_to_build_a_request():
    with pytest.raises(BadRequestError):
        build_authn_request(_config(idp_sso_url=""), now=NOW)


def test_metadata_declares_what_is_actually_true():
    xml = sp_metadata_xml(_config())
    # We verify every assertion, and we do not sign our requests. Both claims
    # have to match the implementation or an administrator configures the IdP
    # to expect something this SP cannot do.
    assert 'WantAssertionsSigned="true"' in xml
    assert 'AuthnRequestsSigned="false"' in xml
    assert f'entityID="{SP_ENTITY_ID}"' in xml
    assert ACS_URL in xml


# ---- the happy path ---------------------------------------------------------

def test_a_signed_assertion_yields_the_identity_it_carries():
    claims = _verify(_sign(_response_xml()))
    assert claims["sub"] == "dana@acme.com"
    assert claims["email"] == "dana@acme.com"
    assert claims["name"] == "Dana Scully"
    assert claims["groups"] == ["data-admins", "everyone"]


def test_the_group_map_decides_the_role_exactly_as_it_does_for_oidc():
    """One mapper for both protocols: a group means the same thing either way."""
    identity = map_identity(_verify(_sign(_response_xml())), _config())
    assert identity.role == "admin"
    assert identity.username == "dana@acme.com"

    unmapped = _response_xml(
        attributes=(
            '<saml:AttributeStatement><saml:Attribute Name="groups">'
            "<saml:AttributeValue>everyone</saml:AttributeValue>"
            "</saml:Attribute></saml:AttributeStatement>"
        )
    )
    assert map_identity(_verify(_sign(unmapped)), _config()).role == "viewer"


def test_clock_skew_inside_a_minute_is_tolerated_on_both_edges():
    encoded = _sign(_response_xml())
    assert _verify(encoded, now=NOW + dt.timedelta(minutes=5, seconds=30))["sub"]
    assert _verify(encoded, now=NOW - dt.timedelta(minutes=1, seconds=30))["sub"]


# ---- the signature ----------------------------------------------------------

def test_an_unsigned_assertion_is_refused():
    encoded = base64.b64encode(_response_xml().encode()).decode()
    with pytest.raises(UnauthorizedError):
        _verify(encoded)


def test_an_assertion_signed_by_a_different_key_is_refused():
    other_key, other_cert = _make_key_and_cert()
    encoded = _sign(_response_xml(), key_pem=other_key, cert_pem=other_cert)
    with pytest.raises(UnauthorizedError, match="signature did not verify"):
        _verify(encoded)


def test_tampering_with_a_signed_assertion_is_caught():
    """The attack the whole module exists to stop: edit the identity, keep the
    signature, and hope nobody recomputes the digest."""
    encoded = _sign(_response_xml())
    raw = base64.b64decode(encoded).replace(b"dana@acme.com", b"admin@acme.com")
    with pytest.raises(UnauthorizedError, match="signature did not verify"):
        _verify(base64.b64encode(raw).decode())


def test_a_second_unsigned_assertion_beside_the_signed_one_is_refused():
    """Signature wrapping: sign one assertion, append another, hope the reader
    picks the wrong one. Two assertions is refused outright."""
    encoded = _sign(_response_xml(assertion_count=2), which=0)
    with pytest.raises(UnauthorizedError, match="single assertion"):
        _verify(encoded)


def test_an_encrypted_assertion_is_refused_by_name_rather_than_ignored():
    xml = (
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="_r" Version="2.0" IssueInstant="{_instant(NOW)}" '
        f'Destination="{ACS_URL}" InResponseTo="{REQUEST_ID}">'
        f"<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>"
        '<samlp:Status><samlp:StatusCode '
        'Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        "<saml:EncryptedAssertion/></samlp:Response>"
    )
    with pytest.raises(UnauthorizedError, match="encrypted"):
        _verify(base64.b64encode(xml.encode()).decode())


# ---- binding the assertion to this sign-in, this SP, and this moment --------

def test_an_assertion_for_a_different_request_is_refused():
    encoded = _sign(_response_xml(subject_in_response_to="_somebody-elses-request"))
    with pytest.raises(UnauthorizedError, match="not confirmed"):
        _verify(encoded)


def test_an_unsolicited_assertion_has_no_request_to_bind_to():
    encoded = _sign(_response_xml(in_response_to=None, subject_in_response_to=None))
    with pytest.raises(UnauthorizedError):
        _verify(encoded)


def test_an_assertion_for_a_different_audience_is_refused():
    encoded = _sign(_response_xml(audience="https://someone-else.example.com/saml"))
    with pytest.raises(UnauthorizedError, match="different application"):
        _verify(encoded)


def test_an_assertion_with_no_audience_restriction_is_refused():
    conditions = (
        f'<saml:Conditions NotBefore="{_instant(NOW - dt.timedelta(minutes=1))}" '
        f'NotOnOrAfter="{_instant(NOW + dt.timedelta(minutes=5))}"/>'
    )
    with pytest.raises(UnauthorizedError, match="named no audience"):
        _verify(_sign(_response_xml(conditions=conditions)))


def test_an_assertion_with_no_conditions_at_all_is_refused():
    with pytest.raises(UnauthorizedError, match="no conditions"):
        _verify(_sign(_response_xml(conditions="")))


def test_an_assertion_recipient_for_another_service_provider_is_refused():
    encoded = _sign(_response_xml(recipient="https://evil.example.com/acs"))
    with pytest.raises(UnauthorizedError, match="not confirmed"):
        _verify(encoded)


def test_a_response_addressed_elsewhere_is_refused():
    encoded = _sign(_response_xml(destination="https://evil.example.com/acs"))
    with pytest.raises(UnauthorizedError, match="addressed somewhere else"):
        _verify(encoded)


def test_an_assertion_from_a_different_issuer_is_refused():
    encoded = _sign(_response_xml(issuer="https://other-idp.example.com/metadata"))
    with pytest.raises(UnauthorizedError, match="different identity provider"):
        _verify(encoded)


def test_an_expired_assertion_is_refused():
    encoded = _sign(_response_xml())
    with pytest.raises(UnauthorizedError, match="took too long"):
        _verify(encoded, now=NOW + dt.timedelta(hours=1))


def test_an_assertion_from_the_future_is_refused():
    encoded = _sign(_response_xml())
    with pytest.raises(UnauthorizedError, match="not valid yet"):
        _verify(encoded, now=NOW - dt.timedelta(hours=1))


def test_a_failed_status_is_reported_rather_than_parsed_further():
    xml = _response_xml(status_code="urn:oasis:names:tc:SAML:2.0:status:AuthnFailed")
    with pytest.raises(UnauthorizedError, match="AuthnFailed"):
        _verify(base64.b64encode(xml.encode()).decode())


# ---- the envelope -----------------------------------------------------------

def test_a_response_that_is_not_xml_is_refused():
    with pytest.raises(UnauthorizedError, match="not valid XML"):
        _verify(base64.b64encode(b"not xml at all").decode())


def test_an_empty_response_is_refused():
    with pytest.raises(UnauthorizedError, match="empty"):
        decode_response("")


def test_an_oversized_response_is_refused_before_it_is_parsed():
    with pytest.raises(UnauthorizedError, match="too large"):
        decode_response("A" * (1024 * 1024))


def test_an_entity_declaration_cannot_reach_the_filesystem():
    """XXE: a document that tries to read a local file must not be able to."""
    xml = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE samlp:Response [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="_r" Version="2.0" InResponseTo="{REQUEST_ID}">'
        "<saml:Issuer>&xxe;</saml:Issuer>"
        '<samlp:Status><samlp:StatusCode '
        'Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        "</samlp:Response>"
    )
    with pytest.raises(UnauthorizedError) as caught:
        _verify(base64.b64encode(xml.encode()).decode())
    assert "root:" not in str(caught.value)


def test_in_response_to_is_read_off_the_envelope_for_lookup_only():
    encoded = _sign(_response_xml())
    assert unverified_in_response_to(encoded) == REQUEST_ID


def test_an_envelope_with_no_in_response_to_names_the_reason():
    xml = _response_xml(in_response_to=None)
    with pytest.raises(UnauthorizedError, match="Provider-initiated"):
        unverified_in_response_to(base64.b64encode(xml.encode()).decode())


# ---- provider differences ---------------------------------------------------

def test_okta_and_entra_attribute_shapes_produce_the_same_identity():
    """Okta sends short names; Entra sends WS-* claim URIs for the same facts.
    Taking the last segment of the name handles both without a vendor switch."""
    okta = claims_from_attributes(
        {
            "email": ["dana@acme.com"],
            "displayName": ["Dana Scully"],
            "groups": ["data-admins"],
        },
        name_id="dana@acme.com",
    )
    entra = claims_from_attributes(
        {
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress": [
                "dana@acme.com"
            ],
            "http://schemas.microsoft.com/identity/claims/displayname": ["Dana Scully"],
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups": [
                "data-admins"
            ],
        },
        name_id="dana@acme.com",
    )
    assert okta == entra
    assert entra["email"] == "dana@acme.com"
    assert entra["name"] == "Dana Scully"
    assert entra["groups"] == ["data-admins"]


def test_a_first_and_last_name_become_a_display_name_when_no_full_name_is_sent():
    claims = claims_from_attributes(
        {"firstName": ["Dana"], "surname": ["Scully"]}, name_id="dana"
    )
    assert claims["name"] == "Dana Scully"


def test_an_email_format_nameid_is_the_email_when_no_attribute_carries_one():
    claims = claims_from_attributes(
        {},
        name_id="dana@acme.com",
        name_id_format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
    )
    assert claims["email"] == "dana@acme.com"


def test_a_persistent_nameid_is_the_subject_without_inventing_an_email():
    claims = claims_from_attributes(
        {},
        name_id="a7f3c2",
        name_id_format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
    )
    assert claims["sub"] == "a7f3c2"
    assert "email" not in claims


# ---- configuration ----------------------------------------------------------

def test_a_bare_base64_certificate_is_accepted_as_well_as_pem():
    """Okta hands over a PEM; Entra's metadata carries unwrapped base64."""
    body = "".join(CERT_PEM.strip().splitlines()[1:-1])
    assert normalise_certificate(body) == normalise_certificate(CERT_PEM)
    assert "BEGIN CERTIFICATE" in normalise_certificate(body)


def test_a_certificate_that_is_neither_pem_nor_base64_is_refused():
    with pytest.raises(BadRequestError, match="neither PEM nor base64"):
        normalise_certificate("this is not a certificate!!")


def test_a_bare_base64_certificate_verifies_a_real_assertion():
    body = "".join(CERT_PEM.strip().splitlines()[1:-1])
    claims = _verify(_sign(_response_xml()), config=_config(idp_x509_cert=body))
    assert claims["sub"] == "dana@acme.com"


def test_settings_with_nothing_set_are_not_configured():
    class Empty:
        pass

    config = config_from_settings(Empty())
    assert is_configured(config) is False
    assert saml_status(config)["supported"] is False


def test_settings_are_read_into_a_usable_config():
    class Settings:
        saml_idp_entity_id = IDP_ENTITY_ID
        saml_idp_sso_url = IDP_SSO_URL
        saml_idp_x509_cert = CERT_PEM
        saml_sp_entity_id = SP_ENTITY_ID
        saml_sp_acs_url = ACS_URL
        saml_group_role_map = '{"data-admins": "admin"}'
        oidc_default_role = "operator"
        oidc_allow_jit = False

    config = config_from_settings(Settings())
    assert is_configured(config)
    assert config.group_role_map == {"data-admins": "admin"}
    # Provisioning defaults are shared with OIDC on purpose.
    assert config.default_role == "operator"
    assert config.allow_jit_provisioning is False
    assert saml_status(config)["supported"] is True


def test_a_malformed_group_role_map_is_empty_rather_than_fatal():
    class Settings:
        saml_group_role_map = "{not json"

    assert config_from_settings(Settings()).group_role_map == {}
