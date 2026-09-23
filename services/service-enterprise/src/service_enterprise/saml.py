"""SAML 2.0 as a service provider, with the signature actually checked.

**Why this exists at all.** Plenty of companies run an identity provider that
speaks SAML and nothing else, or speak SAML because that is what their security
team has already reviewed. OIDC (see `sso.py`) is the better protocol and the
one to prefer; this is here so "we only do SAML" is not a reason the platform
cannot be adopted.

**The rule this module exists to enforce:** every claim returned from here comes
out of the subtree whose signature verified, and nothing else. That is the whole
defence against XML signature wrapping -- an attacker appends an unsigned
assertion beside the signed one and waits for the reader to pick the wrong one.
`verify_response` reads the signed subtree that the verifier hands back and
never re-reads the document it parsed, so there is no second copy to confuse.

**What is checked before an identity is returned.** The signature against the
configured IdP certificate; the response status; the issuer; the audience; the
`InResponseTo` on both response and subject confirmation, against a request this
deployment actually made; the recipient; and three separate expiry windows. Each
one is a rejection somebody could otherwise walk through, so each is a hard
failure rather than a warning.

**Scope, stated plainly.** SP-initiated sign-in only: an unsolicited assertion
has no request of ours to bind to, and accepting one means accepting anything
the IdP's signing key has ever produced. Requests are not signed by us --
Okta and Entra do not require it and this deployment has no SP key -- and
encrypted assertions (`EncryptedAssertion`) are refused by name rather than
ignored.

**The signature library.** XML signature verification is done by `signxml`,
which is pure Python over `lxml` and `cryptography`. The alternative,
`python-xmlsec`, needs the `libxmlsec1` system library, which would make a
native package a prerequisite of `npm run setup` and of CI for everyone,
including the majority who never turn SAML on. What matters is that the
signature is verified by a real implementation rather than by hand; both satisfy
that, and only one of them is installable from a wheel. Hand-rolling XMLDSig
here was never on the table: it is the single most reliable way to ship an
authentication bypass.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from shared_python.errors import BadRequestError, UnauthorizedError

SAML_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
SAMLP_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
MD_NS = "urn:oasis:names:tc:SAML:2.0:metadata"

NAMESPACES = {"saml": SAML_NS, "samlp": SAMLP_NS}

STATUS_SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
BEARER_CONFIRMATION = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
NAMEID_FORMAT_EMAIL = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
REDIRECT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"

# Identity providers disagree about clock accuracy more than they disagree about
# anything else. Sixty seconds matches the leeway the OIDC path already allows.
CLOCK_SKEW = timedelta(seconds=60)

# A SAMLResponse larger than this is not a sign-in, it is someone probing. The
# cap is applied before any parsing so a decompression bomb never reaches lxml.
MAX_RESPONSE_BYTES = 512 * 1024

# The package that does the signature verification, named here once so the
# refusal message and the install instruction cannot drift apart.
SIGNATURE_PACKAGE = "signxml"


class SamlUnavailableError(BadRequestError):
    """Raised when SAML is asked for but its signature library is absent."""


@dataclass
class SamlConfig:
    """One identity provider, and what this deployment is to it.

    `group_role_map` and `default_role` deliberately carry the same names as
    `ProviderConfig` in `sso.py`, because the claim-to-identity mapping is
    shared between the two protocols verbatim. A group that grants `admin` over
    OIDC grants exactly the same role over SAML, which is the only sane answer
    for an organisation that migrates between them.
    """

    # The IdP's entity ID, matched against the assertion's Issuer.
    idp_entity_id: str
    # Where the browser is sent to sign in (HTTP-Redirect binding).
    idp_sso_url: str
    # The IdP's signing certificate, PEM or bare base64 from its metadata. Only
    # this certificate is trusted: a certificate carried inside the response is
    # never used to verify the response that carries it.
    idp_x509_cert: str
    # Our entity ID, matched against the assertion's AudienceRestriction.
    sp_entity_id: str
    # Our assertion consumer service URL, matched against Destination/Recipient.
    sp_acs_url: str
    group_role_map: dict[str, str] = field(default_factory=dict)
    default_role: str = "viewer"
    allow_jit_provisioning: bool = True


@dataclass
class AuthnRequest:
    """Where to send the browser, and the request id to remember."""

    url: str
    request_id: str


# ---- the signature library, imported late and refused clearly ---------------

def signature_library_available() -> bool:
    """Whether XML signatures can be verified in this environment."""
    try:
        import signxml  # noqa: F401
    except ImportError:
        return False
    return True


def _require_signature_library():
    """Return signxml, or refuse by name.

    A missing library must never degrade into "skip the signature check"; it
    degrades into "SAML is off here", which is the same shape as every other
    optional dependency in this repository.
    """
    try:
        from signxml import SignatureConfiguration, XMLVerifier
    except ImportError as exc:  # pragma: no cover - exercised by the status path
        raise SamlUnavailableError(
            f"SAML needs the {SIGNATURE_PACKAGE} package to verify XML signatures, and it "
            f"is not installed here. Install it (pip install '{SIGNATURE_PACKAGE}>=4.5,<5') "
            "and restart, or use OIDC instead."
        ) from exc
    return XMLVerifier, SignatureConfiguration


def _lxml():
    try:
        from lxml import etree
    except ImportError as exc:  # pragma: no cover - signxml depends on lxml
        raise SamlUnavailableError(
            "SAML needs the lxml package to read XML, and it is not installed here."
        ) from exc
    return etree


def _parser():
    """An XML parser with every remote and expanding feature switched off.

    Entity resolution is how a signed-looking document reads `/etc/passwd`, and
    network access is how it makes the server fetch a URL of the sender's
    choosing. Neither is needed to read an assertion.
    """
    etree = _lxml()
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )


# ---- configuration ----------------------------------------------------------

def _group_role_map(raw: str | None) -> dict[str, str]:
    import json

    try:
        parsed = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}


def config_from_settings(settings) -> SamlConfig:
    """Read one identity provider out of the deployment's settings.

    Here rather than in the gateway so the status endpoint and the sign-in flow
    cannot end up disagreeing about whether SAML is configured.
    """
    return SamlConfig(
        idp_entity_id=getattr(settings, "saml_idp_entity_id", None) or "",
        idp_sso_url=getattr(settings, "saml_idp_sso_url", None) or "",
        idp_x509_cert=getattr(settings, "saml_idp_x509_cert", None) or "",
        sp_entity_id=getattr(settings, "saml_sp_entity_id", None) or "",
        sp_acs_url=getattr(settings, "saml_sp_acs_url", None) or "",
        group_role_map=_group_role_map(getattr(settings, "saml_group_role_map", None)),
        # SAML reuses the OIDC provisioning defaults rather than duplicating
        # them: the role a new person gets should not depend on the protocol
        # they arrived by.
        default_role=getattr(settings, "oidc_default_role", "viewer"),
        allow_jit_provisioning=getattr(settings, "oidc_allow_jit", True),
    )


def is_configured(config: SamlConfig | None) -> bool:
    return bool(
        config
        and config.idp_entity_id
        and config.idp_sso_url
        and config.idp_x509_cert
        and config.sp_entity_id
        and config.sp_acs_url
    )


def normalise_certificate(raw: str) -> str:
    """Accept a PEM block or the bare base64 an IdP's metadata shows.

    Okta's admin screen hands over a PEM; Entra's federation metadata carries
    the same bytes as a single unwrapped base64 line inside `<X509Certificate>`.
    Making the caller convert between them is a configuration error waiting to
    happen, so both are accepted here.
    """
    text = (raw or "").strip()
    if not text:
        raise BadRequestError("No identity-provider certificate is configured.")
    if "-----BEGIN CERTIFICATE-----" in text:
        # Normalising the trailing newline too, so the same certificate given
        # in either form compares equal after this.
        return text + "\n"
    body = re.sub(r"\s+", "", text)
    try:
        base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BadRequestError(
            "The identity-provider certificate is neither PEM nor base64."
        ) from exc
    lines = "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN CERTIFICATE-----\n{lines}\n-----END CERTIFICATE-----\n"


def saml_status(config: SamlConfig | None = None) -> dict[str, Any]:
    """What SAML can do in this deployment, right now.

    Three different answers that used to be one word: the code is present, the
    signature library may or may not be installed, and a provider may or may not
    be configured. Collapsing them would put the deployment in the position of
    guessing which one is its problem.
    """
    library = signature_library_available()
    configured = is_configured(config)
    if not library:
        reason = (
            f"SAML is implemented, but the {SIGNATURE_PACKAGE} package that verifies XML "
            "signatures is not installed here. An assertion whose signature is not checked "
            "is an authentication bypass, so SAML stays off until it is."
        )
    elif not configured:
        reason = (
            "SAML is implemented and its signature library is present, but no identity "
            "provider is configured on this deployment."
        )
    else:
        reason = "SAML sign-in is configured and available."
    return {
        "supported": bool(library and configured),
        "implemented": True,
        "signature_library": SIGNATURE_PACKAGE,
        "signature_library_available": library,
        "configured": configured,
        "reason": reason,
        "notes": (
            "Service-provider-initiated sign-in only; unsolicited assertions are refused "
            "because there is no request of ours to bind them to. Encrypted assertions are "
            "not supported and are refused by name."
        ),
        "alternative": "OIDC is the preferred protocol where the provider offers both.",
    }


# ---- the request we send ----------------------------------------------------

def _instant(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_authn_request(config: SamlConfig, *, now: datetime | None = None) -> AuthnRequest:
    """Build the redirect that starts a sign-in.

    The id is remembered by the caller and demanded back in the response's
    `InResponseTo`; that binding is what makes a stolen or replayed assertion
    useless here.
    """
    if not is_configured(config):
        raise BadRequestError("SAML is not configured on this deployment.")

    # A SAML ID must be an xsd:ID, which may not start with a digit.
    request_id = f"_{secrets.token_hex(16)}"
    moment = _instant(now or datetime.now(UTC))
    xml = (
        '<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{request_id}" Version="2.0" IssueInstant="{moment}" '
        f'Destination="{_xml_attr(config.idp_sso_url)}" '
        f'ProtocolBinding="{POST_BINDING}" '
        f'AssertionConsumerServiceURL="{_xml_attr(config.sp_acs_url)}">'
        f"<saml:Issuer>{_xml_text(config.sp_entity_id)}</saml:Issuer>"
        "</samlp:AuthnRequest>"
    )
    # HTTP-Redirect carries the request raw-deflated then base64'd (wbits=-15 is
    # raw DEFLATE without the zlib header, which is what the binding specifies).
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    deflated = compressor.compress(xml.encode("utf-8")) + compressor.flush()
    query = urlencode({"SAMLRequest": base64.b64encode(deflated).decode("ascii")})
    separator = "&" if "?" in config.idp_sso_url else "?"
    return AuthnRequest(url=f"{config.idp_sso_url}{separator}{query}", request_id=request_id)


def _xml_attr(value: str) -> str:
    return _xml_text(value).replace('"', "&quot;")


def _xml_text(value: str) -> str:
    return (
        str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def sp_metadata_xml(config: SamlConfig) -> str:
    """The metadata an administrator uploads to the identity provider.

    `WantAssertionsSigned` is true and `AuthnRequestsSigned` is false, and both
    are the truth: this verifies every assertion it accepts, and does not sign
    the requests it sends because it holds no service-provider key.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<md:EntityDescriptor xmlns:md="{MD_NS}" '
        f'entityID="{_xml_attr(config.sp_entity_id)}">'
        '<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        f'<md:NameIDFormat>{NAMEID_FORMAT_EMAIL}</md:NameIDFormat>'
        f'<md:AssertionConsumerService Binding="{POST_BINDING}" '
        f'Location="{_xml_attr(config.sp_acs_url)}" index="0" isDefault="true"/>'
        "</md:SPSSODescriptor></md:EntityDescriptor>"
    )


# ---- claim names, across providers -----------------------------------------

# Okta sends `email` and `groups`; Entra sends the same facts under WS-* claim
# URIs. Rather than a per-vendor switch that a third vendor immediately breaks,
# the last segment of a URI-style name is taken and matched against these
# aliases -- which covers both tested profiles and most others by construction.
EMAIL_ALIASES = ("email", "emailaddress", "mail", "upn")
NAME_ALIASES = ("displayname", "name", "cn", "commonname")
GIVEN_NAME_ALIASES = ("givenname", "firstname")
SURNAME_ALIASES = ("surname", "lastname", "sn")
GROUP_ALIASES = ("groups", "group", "memberof", "role", "roles")
USERNAME_ALIASES = (
    "preferred_username",
    "username",
    "uid",
    "samaccountname",
    "nameidentifier",
    "upn",
)


def _short_name(attribute_name: str) -> str:
    """`http://schemas.xmlsoap.org/.../emailaddress` -> `emailaddress`."""
    text = (attribute_name or "").strip()
    if not text:
        return ""
    tail = re.split(r"[/#]", text)[-1]
    return tail.strip().lower()


def claims_from_attributes(
    attributes: dict[str, list[str]],
    *,
    name_id: str,
    name_id_format: str | None = None,
) -> dict[str, Any]:
    """Turn a SAML attribute statement into the claim shape `sso.map_identity`
    already understands, so both protocols resolve identity by one code path."""
    indexed: dict[str, list[str]] = {}
    for raw_name, values in attributes.items():
        short = _short_name(raw_name)
        if short:
            indexed.setdefault(short, []).extend(values)

    def first(aliases: tuple[str, ...]) -> str | None:
        for alias in aliases:
            for value in indexed.get(alias, []):
                if value and value.strip():
                    return value.strip()
        return None

    groups: list[str] = []
    for alias in GROUP_ALIASES:
        if alias in indexed:
            groups = [v.strip() for v in indexed[alias] if v and v.strip()]
            break

    display_name = first(NAME_ALIASES)
    if not display_name:
        given, surname = first(GIVEN_NAME_ALIASES), first(SURNAME_ALIASES)
        display_name = " ".join(part for part in (given, surname) if part) or None

    email = first(EMAIL_ALIASES)
    # An emailAddress-format NameID *is* the email, and many providers send no
    # separate attribute for it.
    if not email and name_id_format == NAMEID_FORMAT_EMAIL:
        email = name_id

    claims: dict[str, Any] = {
        # The NameID is the only identifier the specification promises is
        # stable for this subject, so it is the subject here too.
        "sub": name_id,
        "email": email,
        "name": display_name,
        "groups": groups,
    }
    username = first(USERNAME_ALIASES) or email or name_id
    claims["preferred_username"] = username
    return {key: value for key, value in claims.items() if value not in (None, [])}


# ---- the response we accept -------------------------------------------------

def _parse_instant(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def decode_response(raw: str) -> bytes:
    """Base64-decode the `SAMLResponse` form field, with a size ceiling."""
    if not raw or not raw.strip():
        raise UnauthorizedError("The sign-in response was empty.")
    if len(raw) > MAX_RESPONSE_BYTES:
        raise UnauthorizedError("That sign-in response is too large to be genuine.")
    try:
        decoded = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise UnauthorizedError("The sign-in response could not be decoded.") from exc
    if not decoded:
        raise UnauthorizedError("The sign-in response was empty.")
    if len(decoded) > MAX_RESPONSE_BYTES:
        raise UnauthorizedError("That sign-in response is too large to be genuine.")
    return decoded


def unverified_in_response_to(raw_response: str) -> str:
    """Read `InResponseTo` off the envelope, before anything is verified.

    Named for what it is. The caller needs it for exactly one thing: finding the
    stored request whose id is then handed to `verify_response`, which checks
    the *signed* assertion against it. Choosing this value therefore only
    chooses which of our own requests the signature is checked against -- the
    signature still has to hold, and the signed assertion's own `InResponseTo`
    still has to match. Using it for anything else would undo that.
    """
    etree = _lxml()
    payload = decode_response(raw_response)
    try:
        document = etree.fromstring(payload, parser=_parser())
    except etree.XMLSyntaxError as exc:
        raise UnauthorizedError("The sign-in response was not valid XML.") from exc
    if etree.QName(document).namespace != SAMLP_NS:
        raise UnauthorizedError("That was not a SAML response.")
    request_id = document.get("InResponseTo")
    if not request_id:
        raise UnauthorizedError(
            "That assertion was not sent in response to a sign-in started here. "
            "Provider-initiated SAML is not accepted."
        )
    return request_id


def _status_message(document) -> str:
    code = document.find("./samlp:Status/samlp:StatusCode", NAMESPACES)
    value = (code.get("Value") if code is not None else None) or "an unspecified failure"
    message = document.find("./samlp:Status/samlp:StatusMessage", NAMESPACES)
    detail = (message.text or "").strip() if message is not None else ""
    short = value.rsplit(":", 1)[-1]
    return f"The identity provider refused the sign-in ({short}){f': {detail}' if detail else ''}."


def verify_response(
    raw_response: str,
    *,
    config: SamlConfig,
    expected_request_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify a SAMLResponse and return the claims from its signed assertion.

    Every return path below either raises or reads from `signed_xml`, the
    subtree whose signature verified. The parsed document is used only for the
    protocol-level status and for locating the assertion to verify -- never for
    a value that ends up in an identity.
    """
    etree = _lxml()
    XMLVerifier, SignatureConfiguration = _require_signature_library()

    if not is_configured(config):
        raise BadRequestError("SAML is not configured on this deployment.")
    if not expected_request_id:
        # No remembered request means this is unsolicited, which this SP does
        # not accept -- see the module docstring.
        raise UnauthorizedError("This sign-in did not start here.")

    payload = decode_response(raw_response)
    try:
        document = etree.fromstring(payload, parser=_parser())
    except etree.XMLSyntaxError as exc:
        raise UnauthorizedError("The sign-in response was not valid XML.") from exc

    if etree.QName(document).namespace != SAMLP_NS or etree.QName(document).localname != "Response":
        raise UnauthorizedError("That was not a SAML response.")

    if document.find("./saml:EncryptedAssertion", NAMESPACES) is not None:
        raise UnauthorizedError(
            "This assertion is encrypted, and encrypted assertions are not supported here. "
            "Turn off assertion encryption for this application, or use OIDC."
        )

    status = document.find("./samlp:Status/samlp:StatusCode", NAMESPACES)
    if status is None or status.get("Value") != STATUS_SUCCESS:
        raise UnauthorizedError(_status_message(document))

    # Bind the envelope to our request before spending work on the signature.
    in_response_to = document.get("InResponseTo")
    if in_response_to and in_response_to != expected_request_id:
        raise UnauthorizedError("This sign-in did not start here.")
    destination = document.get("Destination")
    if destination and destination.rstrip("/") != config.sp_acs_url.rstrip("/"):
        raise UnauthorizedError("That sign-in response was addressed somewhere else.")

    assertions = document.findall("./saml:Assertion", NAMESPACES)
    if len(assertions) != 1:
        # Zero is nothing to verify. More than one is the shape of a wrapping
        # attack, and picking one of them is exactly the mistake to avoid.
        raise UnauthorizedError("That sign-in response did not carry a single assertion.")

    certificate = normalise_certificate(config.idp_x509_cert)
    # Only the assertion's own signature counts. A response-level signature
    # over an unsigned assertion would leave the assertion swappable.
    expect = SignatureConfiguration(
        require_x509=True,
        location=f".//{{{SAML_NS}}}Assertion/",
        expect_references=1,
    )
    try:
        verified = XMLVerifier().verify(
            payload,
            x509_cert=certificate,
            expect_config=expect,
            id_attribute="ID",
        )
    except Exception as exc:  # noqa: BLE001 - every failure here is a failed sign-in
        raise UnauthorizedError(f"That assertion's signature did not verify: {exc}") from exc

    signed = verified.signed_xml if not isinstance(verified, list) else verified[0].signed_xml
    if signed is None or etree.QName(signed).localname != "Assertion":
        raise UnauthorizedError("The signature did not cover the assertion.")

    return _claims_from_signed_assertion(
        signed,
        config=config,
        expected_request_id=expected_request_id,
        now=now or datetime.now(UTC),
        etree=etree,
    )


def _claims_from_signed_assertion(
    assertion,
    *,
    config: SamlConfig,
    expected_request_id: str,
    now: datetime,
    etree,
) -> dict[str, Any]:
    """Validate the signed assertion's conditions and read its claims."""
    issuer = assertion.find("./saml:Issuer", NAMESPACES)
    issuer_text = (issuer.text or "").strip() if issuer is not None else ""
    if issuer_text != config.idp_entity_id:
        raise UnauthorizedError("That assertion came from a different identity provider.")

    subject = assertion.find("./saml:Subject", NAMESPACES)
    name_id_element = subject.find("./saml:NameID", NAMESPACES) if subject is not None else None
    name_id = (name_id_element.text or "").strip() if name_id_element is not None else ""
    if not name_id:
        raise UnauthorizedError("The identity provider did not say who signed in.")

    _check_subject_confirmation(
        subject, config=config, expected_request_id=expected_request_id, now=now
    )
    _check_conditions(assertion, config=config, now=now)

    attributes: dict[str, list[str]] = {}
    for attribute in assertion.findall(
        "./saml:AttributeStatement/saml:Attribute", NAMESPACES
    ):
        key = attribute.get("Name") or attribute.get("FriendlyName") or ""
        values = [
            (value.text or "").strip()
            for value in attribute.findall("./saml:AttributeValue", NAMESPACES)
        ]
        if key:
            attributes.setdefault(key, []).extend(v for v in values if v)

    return claims_from_attributes(
        attributes,
        name_id=name_id,
        name_id_format=name_id_element.get("Format") if name_id_element is not None else None,
    )


def _check_subject_confirmation(
    subject, *, config: SamlConfig, expected_request_id: str, now: datetime
) -> None:
    """At least one bearer confirmation must name us, our request, and a future.

    All three together: a confirmation that is merely unexpired still lets an
    assertion minted for another service provider be replayed at this one.
    """
    if subject is None:
        raise UnauthorizedError("That assertion had no subject.")

    # A confirmation that named us and named this sign-in, and failed only on
    # time, is somebody who took too long -- a different thing from an
    # assertion aimed elsewhere, and worth saying differently. They are told to
    # start again; everyone else is told nothing they did not already know.
    expired = False
    for confirmation in subject.findall("./saml:SubjectConfirmation", NAMESPACES):
        if confirmation.get("Method") != BEARER_CONFIRMATION:
            continue
        data = confirmation.find("./saml:SubjectConfirmationData", NAMESPACES)
        if data is None:
            continue
        recipient = data.get("Recipient")
        if recipient and recipient.rstrip("/") != config.sp_acs_url.rstrip("/"):
            continue
        if data.get("InResponseTo") != expected_request_id:
            continue
        not_on_or_after = _parse_instant(data.get("NotOnOrAfter"))
        if not_on_or_after is None:
            # A bearer confirmation with no expiry is one that never expires.
            continue
        if now >= not_on_or_after + CLOCK_SKEW:
            expired = True
            continue
        return
    if expired:
        raise UnauthorizedError("This sign-in took too long. Start again.")
    raise UnauthorizedError(
        "That assertion was not confirmed for this application and this sign-in."
    )


def _check_conditions(assertion, *, config: SamlConfig, now: datetime) -> None:
    conditions = assertion.find("./saml:Conditions", NAMESPACES)
    if conditions is None:
        raise UnauthorizedError("That assertion carried no conditions, so it cannot be trusted.")

    not_before = _parse_instant(conditions.get("NotBefore"))
    if not_before is not None and now + CLOCK_SKEW < not_before:
        raise UnauthorizedError("That assertion is not valid yet.")
    not_on_or_after = _parse_instant(conditions.get("NotOnOrAfter"))
    if not_on_or_after is not None and now >= not_on_or_after + CLOCK_SKEW:
        raise UnauthorizedError("That sign-in took too long. Start again.")

    restrictions = conditions.findall("./saml:AudienceRestriction", NAMESPACES)
    if not restrictions:
        raise UnauthorizedError("That assertion named no audience, so it was not meant for us.")
    audiences = {
        (audience.text or "").strip()
        for restriction in restrictions
        for audience in restriction.findall("./saml:Audience", NAMESPACES)
    }
    if config.sp_entity_id not in audiences:
        raise UnauthorizedError("That assertion was issued for a different application.")
