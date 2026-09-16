"""Connectors as declarations.

Phase 04 proved the leverage: Stripe, HubSpot, Shopify, Salesforce and Google
Sheets are forty lines each because they are presets over one tested REST
client. This module finishes that thought -- a SaaS connector stops being code
at all and becomes a YAML file describing where the records are, how the API
paginates, and which header carries the token.

Three things make that safe rather than merely convenient:

* **The schema is enforced at import.** A malformed manifest raises when the
  package loads, so it cannot ship. `test_manifests.py` asserts every file in
  the catalogue loads, which is the same check the build performs.
* **Types name the Phase 08 lattice.** A manifest that says `TIMESTAMP` means
  the platform's timestamp, with tz-awareness part of the type -- not a string
  the loader guesses at.
* **Every manifest declares its tier.** A file written from a vendor's docs and
  never executed says so, and that claim travels to the picker and the run log.

The manifest is deliberately *not* a general-purpose HTTP DSL. It describes the
shapes this platform's REST client already handles; anything a manifest cannot
express is a hand-written connector, which is the honest outcome rather than a
DSL that grows until it is a programming language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from service_connectors.protocol import (
    CATEGORIES,
    ConfigField,
    ConnectorSpec,
    StreamRef,
    Tier,
)

#: Where the shipped manifests live.
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"

#: Type names a manifest may use. They are the Phase 08 lattice's names, which
#: is why 08 had to come first: a manifest saying `TIMESTAMP` means the
#: platform's timestamp, tz-awareness included, not a hint for a later guess.
MANIFEST_TYPES = (
    "STRING", "INTEGER", "BIGINT", "FLOAT", "DECIMAL", "BOOLEAN",
    "DATE", "TIME", "TIMESTAMP", "JSON", "ARRAY", "UUID", "BYTES",
)


class _Strict(BaseModel):
    """Unknown keys are refused, not ignored.

    A typo in a manifest that silently does nothing is the failure mode this
    whole file exists to prevent: the connector ships, looks fine, and quietly
    paginates only the first page.
    """

    model_config = ConfigDict(extra="forbid")


class AuthSpec(_Strict):
    kind: Literal["none", "bearer", "api_key", "basic", "oauth2_client_credentials"] = "bearer"
    #: Where the credential goes for `api_key`.
    placement: Literal["header", "query"] = "header"
    header: str = "Authorization"
    query_param: str = "api_key"
    #: How the credential is written, e.g. "Bearer {token}" or "Klaviyo-API-Key {token}".
    template: str = "Bearer {token}"
    #: For basic auth, the field holding the username.
    username_field: str | None = None
    #: For OAuth client credentials.
    token_url: str | None = None
    scopes: tuple[str, ...] = ()

    @field_validator("template")
    @classmethod
    def _must_carry_the_token(cls, value: str) -> str:
        if "{token}" not in value:
            raise ValueError(
                "An auth template has to say where the credential goes, with {token}."
            )
        return value


class RateLimit(_Strict):
    requests_per_second: float = Field(default=5.0, gt=0, le=1000)
    burst: int = Field(default=10, ge=1, le=10_000)
    retry_on: tuple[int, ...] = (429, 500, 502, 503, 504)
    backoff: Literal["exponential", "linear", "none"] = "exponential"


class Pagination(_Strict):
    """How this endpoint hands out the next page.

    The parameter names are part of the declaration, not decoration: an API
    that wants `page[cursor]` and receives `cursor` answers with page one
    again, and a connector that does not notice collects the same rows until it
    reaches `MAX_PAGES`. `rest.PageParams` reads every one of these.
    """

    kind: Literal["none", "page", "offset", "cursor", "next_url", "link_header"] = "none"
    page_param: str = "page"
    #: Unset means the convention for this strategy -- `per_page` beside a page
    #: number, `limit` beside an offset. Distinct from naming one explicitly.
    size_param: str | None = None
    offset_param: str = "offset"
    cursor_param: str = "cursor"
    #: Dotted path to the next cursor in the response body.
    cursor_path: str | None = None
    page_size: int = Field(default=100, ge=1, le=10_000)
    start_page: int = Field(default=1, ge=0)
    #: False for the APIs that reject an unknown page-size parameter.
    send_page_size: bool = True

    def model_post_init(self, _context: Any) -> None:
        # Checked here rather than with a field validator: a validator on
        # `cursor_path` never runs when the key is absent, which is precisely
        # the manifest this is meant to catch.
        if self.kind == "cursor" and not self.cursor_path:
            raise ValueError(
                "Cursor pagination needs a cursor_path saying where the next cursor "
                "is in the response."
            )
        if self.kind == "next_url" and not self.cursor_path:
            raise ValueError(
                "next_url pagination needs a cursor_path saying where the address of "
                "the next page is in the response."
            )


class Incremental(_Strict):
    """How this stream asks for only what changed."""

    cursor_field: str
    param: str
    #: How the value is written into the request, e.g. "greater-than(updated,{value})".
    template: str = "{value}"
    #: Where the value goes.
    placement: Literal["query", "body"] = "query"

    @field_validator("template")
    @classmethod
    def _must_carry_the_value(cls, value: str) -> str:
        if "{value}" not in value:
            raise ValueError("An incremental template has to say where the cursor goes, with {value}.")
        return value


class FieldSpec(_Strict):
    type: str = "STRING"
    #: The name this becomes in the output frame, when it differs from the path.
    rename: str | None = None
    tz_aware: bool = False
    description: str | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value.upper() not in MANIFEST_TYPES:
            raise ValueError(
                f"'{value}' is not a type a manifest can declare. "
                f"Use one of: {', '.join(MANIFEST_TYPES)}."
            )
        return value.upper()


class StreamSpec(_Strict):
    name: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1)
    method: Literal["GET", "POST"] = "GET"
    label: str | None = None
    #: Dotted path to the array of records in the response.
    records_path: str | None = None
    primary_key: str | None = None
    pagination: Pagination = Field(default_factory=Pagination)
    incremental: Incremental | None = None
    #: Extra query parameters this stream always sends.
    params: dict[str, str] = Field(default_factory=dict)
    #: The columns the vendor documents, keyed by their path in the response.
    schema_fields: dict[str, FieldSpec] = Field(default_factory=dict, alias="schema")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("name")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"'{value}' is not usable as a stream name.")
        return value


class ConfigFieldSpec(_Strict):
    name: str
    label: str
    kind: Literal["string", "secret", "number", "boolean", "select", "text"] = "string"
    required: bool = True
    default: Any = None
    help: str | None = None
    options: tuple[str, ...] = ()
    placeholder: str | None = None


class Manifest(_Strict):
    """One connector, declared.

    The descriptions on these fields are not decoration: `docs/adding-a-connector.md`
    is generated from them, so a field documented here is a field documented for
    whoever writes the next manifest.
    """

    key: str = Field(
        min_length=1, max_length=60,
        description="Lower case identifier. Becomes the connector type in the API.",
    )
    label: str = Field(
        min_length=1, max_length=80, description="What a person sees in the picker."
    )
    category: str = Field(
        default="saas", description="Which section of the catalogue it appears in."
    )
    description: str = Field(
        min_length=1, max_length=400,
        description="One sentence saying what it reads. Shown on the card.",
    )
    docs_url: str | None = Field(
        default=None, description="The vendor's API reference, linked from the card."
    )
    base_url: str = Field(
        min_length=1,
        description=(
            "The API root. May contain `{placeholders}` filled from config_fields -- "
            "a subdomain, a region, an account id."
        ),
    )
    auth: AuthSpec = Field(
        default_factory=AuthSpec,
        description="How the credential is sent. Defaults to a bearer token.",
    )
    default_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Headers every request carries, such as an API version.",
    )
    rate_limit: RateLimit = Field(
        default_factory=RateLimit, description="How hard to push before backing off."
    )
    streams: tuple[StreamSpec, ...] = Field(
        min_length=1, description="The endpoints this connector reads. At least one."
    )
    config_fields: tuple[ConfigFieldSpec, ...] = Field(
        default=(),
        description=(
            "Settings beyond the credential -- an account id, a region, a subdomain. "
            "Every `{placeholder}` used above needs one."
        ),
    )
    tier: Literal[1, 2, 3, 4] = Field(
        default=4,
        description="How verified this is. 4 means never executed here, and is the default.",
    )
    verified_by: str | None = Field(
        default=None,
        description="The test file backing a tier above 4. Required for tiers 1-3.",
    )

    @field_validator("key")
    @classmethod
    def _key_shape(cls, value: str) -> str:
        if not value.replace("_", "").isalnum() or not value.islower():
            raise ValueError(
                f"'{value}' is not usable as a connector key: lower case, letters, "
                "numbers and underscores."
            )
        return value

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError(f"'{value}' is not a category. Use one of: {', '.join(CATEGORIES)}.")
        return value

    @field_validator("streams")
    @classmethod
    def _unique_stream_names(cls, value: tuple[StreamSpec, ...]) -> tuple[StreamSpec, ...]:
        names = [stream.name for stream in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Two streams share a name: {', '.join(duplicates)}.")
        return value

    def model_post_init(self, _context: Any) -> None:
        if self.tier != 4 and not self.verified_by:
            # A claim above "unverified" has to say what backs it, or the tier
            # system is decoration.
            raise ValueError(
                f"{self.key} claims tier {self.tier} but does not say what verified it. "
                "Set verified_by, or leave it at tier 4."
            )


class ManifestError(Exception):
    """A manifest that cannot be trusted, with the file and the reason."""


@dataclass
class LoadedManifest:
    manifest: Manifest
    source: Path | None = None
    warnings: list[str] = field(default_factory=list)


def parse(document: dict[str, Any], source: Path | None = None) -> Manifest:
    """Validate one manifest document, or say exactly what is wrong with it."""
    try:
        return Manifest.model_validate(document)
    except ValidationError as exc:
        where = f" in {source.name}" if source else ""
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ManifestError(f"Invalid connector manifest{where}: {problems}") from exc


def load_file(path: Path) -> Manifest:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ManifestError(f"{path.name} should be a mapping, not a {type(document).__name__}.")
    return parse(document, source=path)


def load_all(directory: Path | None = None) -> list[Manifest]:
    """Every shipped manifest, in a stable order.

    Raises on the first bad one rather than skipping it: a connector that
    silently failed to load would be missing from the picker with no explanation,
    and somebody would spend an afternoon on it.
    """
    root = directory or MANIFEST_DIR
    if not root.exists():
        return []
    return [load_file(path) for path in sorted(root.glob("*.yaml"))]


# ------------------------------------------------------- manifest -> spec


def to_spec(manifest: Manifest) -> ConnectorSpec:
    """The catalogue entry a manifest describes."""
    fields: list[ConfigField] = list(_credential_fields(manifest))
    for extra in manifest.config_fields:
        fields.append(
            ConfigField(
                name=extra.name,
                label=extra.label,
                kind=extra.kind,
                required=extra.required,
                default=extra.default,
                help=extra.help,
                options=tuple(extra.options),
                placeholder=extra.placeholder,
            )
        )

    capabilities = {"test", "discover", "schema", "read"}
    if any(stream.incremental for stream in manifest.streams):
        capabilities.add("incremental")

    return ConnectorSpec(
        type=manifest.key,
        label=manifest.label,
        category=manifest.category,
        description=manifest.description,
        config_fields=tuple(fields),
        capabilities=frozenset(capabilities),
        documentation_url=manifest.docs_url,
        tier=Tier(manifest.tier),
        verified_by=manifest.verified_by,
        origin="manifest",
    )


def _credential_fields(manifest: Manifest) -> list[ConfigField]:
    auth = manifest.auth
    if auth.kind == "none":
        return []
    if auth.kind == "basic":
        return [
            ConfigField(
                name="auth_username",
                label="Username",
                help="The account this connects as.",
            ),
            ConfigField(name="auth_secret", label="Password", kind="secret"),
        ]
    if auth.kind == "oauth2_client_credentials":
        return [
            ConfigField(name="client_id", label="Client ID"),
            ConfigField(name="client_secret", label="Client secret", kind="secret"),
        ]
    label = "API key" if auth.kind == "api_key" else "Access token"
    return [
        ConfigField(
            name="auth_secret",
            label=label,
            kind="secret",
            help=f"Stored encrypted. {manifest.label} issues this in its settings.",
        )
    ]


def streams_of(manifest: Manifest) -> tuple[StreamRef, ...]:
    return tuple(
        StreamRef(
            name=stream.name,
            kind="endpoint",
            detail={
                "path": stream.path,
                "method": stream.method,
                "records_path": stream.records_path,
                "primary_key": stream.primary_key,
                "label": stream.label or stream.name.replace("_", " ").title(),
                "incremental": bool(stream.incremental),
            },
        )
        for stream in manifest.streams
    )
