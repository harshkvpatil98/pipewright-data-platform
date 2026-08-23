"""The SaaS tools teams actually keep their data in.

Every one of these is a JSON API, so none of them needs a new client -- they are
the REST connector with the parts that differ filled in: where the records sit
in the response, how the API paginates, which header carries the token. That is
the entire return on building the SDK first. A new SaaS source is a spec and a
preset, not a project.

What is *not* claimed: none of these has been run against a live account, because
that needs credentials this deployment does not have. The request shapes come
from each vendor's documented API. Treat the first run against a real account as
the real test -- which is what `test()` is for.
"""

from __future__ import annotations

from typing import Any

from service_connectors.adapters.rest import RestConnector
from service_connectors.protocol import ConfigField, ConnectorSpec, StreamRef


class PresetRestConnector(RestConnector):
    """A REST connector with the vendor-specific parts already answered."""

    def __init__(self, spec: ConnectorSpec, preset: dict[str, Any], streams: tuple[StreamRef, ...]):
        self.spec = spec
        self._preset = preset
        self._streams = streams

    def _resolved(self, config: dict[str, Any]) -> dict[str, Any]:
        """The user's settings, over the preset, so a preset can be overridden."""
        merged = {**self._preset, **{k: v for k, v in config.items() if v not in (None, "")}}
        # The account-specific part of a base URL is a user setting; substitute
        # it rather than making every vendor's connector build its own URL.
        template = str(merged.get("base_url") or "")
        if "{" in template:
            try:
                merged["base_url"] = template.format(**{k: str(v) for k, v in merged.items()})
            except KeyError:
                pass  # A missing placeholder is caught by config validation.
        return merged

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        """The objects this API exposes.

        Hard-coded rather than fetched: these vendors publish a fixed set of
        top-level objects, and asking the API for its own schema costs a round
        trip to learn something that does not change.
        """
        return list(self._streams)

    def test(self, config: dict[str, Any]):
        return super().test(self._resolved(config))

    def read(self, config: dict[str, Any], stream: StreamRef | None = None, **kwargs: Any):
        resolved = self._resolved(config)
        if stream is not None:
            resolved["path"] = str(stream.detail.get("path") or stream.name)
            if stream.detail.get("records_path"):
                resolved["records_path"] = stream.detail["records_path"]
        return super().read(resolved, None, **kwargs)


def _token_fields(label: str = "API token") -> tuple[ConfigField, ...]:
    return (
        ConfigField("auth_secret", label, kind="secret"),
        ConfigField(
            "page_size", "Page size", kind="number", required=False, default=100
        ),
    )


def _streams(*entries: tuple[str, str, str | None]) -> tuple[StreamRef, ...]:
    return tuple(
        StreamRef(
            name=name,
            kind="object",
            detail={"path": path, **({"records_path": records} if records else {})},
        )
        for name, path, records in entries
    )


STRIPE = PresetRestConnector(
    ConnectorSpec(
        type="stripe",
        label="Stripe",
        category="saas",
        description="Read customers, charges, invoices, and subscriptions from Stripe.",
        config_fields=_token_fields("Secret key"),
        capabilities=frozenset({"test", "discover", "read"}),
        documentation_url="https://stripe.com/docs/api",
    ),
    preset={
        "base_url": "https://api.stripe.com/v1",
        "path": "/customers",
        "records_path": "data",
        "auth_method": "bearer",
        "pagination": "cursor",
        "cursor_path": "data.-1.id",
    },
    streams=_streams(
        ("customers", "/customers", "data"),
        ("charges", "/charges", "data"),
        ("invoices", "/invoices", "data"),
        ("subscriptions", "/subscriptions", "data"),
        ("products", "/products", "data"),
    ),
)

HUBSPOT = PresetRestConnector(
    ConnectorSpec(
        type="hubspot",
        label="HubSpot",
        category="saas",
        description="Read contacts, companies, and deals from HubSpot.",
        config_fields=_token_fields("Private app token"),
        capabilities=frozenset({"test", "discover", "read"}),
        documentation_url="https://developers.hubspot.com/docs/api/crm/understanding-the-crm",
    ),
    preset={
        "base_url": "https://api.hubapi.com",
        "path": "/crm/v3/objects/contacts",
        "records_path": "results",
        "auth_method": "bearer",
        "pagination": "cursor",
        "cursor_path": "paging.next.after",
    },
    streams=_streams(
        ("contacts", "/crm/v3/objects/contacts", "results"),
        ("companies", "/crm/v3/objects/companies", "results"),
        ("deals", "/crm/v3/objects/deals", "results"),
        ("tickets", "/crm/v3/objects/tickets", "results"),
    ),
)

SHOPIFY = PresetRestConnector(
    ConnectorSpec(
        type="shopify",
        label="Shopify",
        category="saas",
        description="Read orders, products, and customers from a Shopify store.",
        config_fields=(
            ConfigField(
                "shop",
                "Shop name",
                placeholder="my-store",
                help="The part before .myshopify.com.",
            ),
            ConfigField("auth_secret", "Admin API access token", kind="secret"),
            ConfigField("page_size", "Page size", kind="number", required=False, default=100),
        ),
        capabilities=frozenset({"test", "discover", "read"}),
        documentation_url="https://shopify.dev/docs/api/admin-rest",
    ),
    preset={
        "base_url": "https://{shop}.myshopify.com/admin/api/2024-01",
        "path": "/orders.json",
        "records_path": "orders",
        "auth_method": "api_key_header",
        "auth_header_name": "X-Shopify-Access-Token",
        "pagination": "link_header",
    },
    streams=_streams(
        ("orders", "/orders.json", "orders"),
        ("products", "/products.json", "products"),
        ("customers", "/customers.json", "customers"),
    ),
)

SALESFORCE = PresetRestConnector(
    ConnectorSpec(
        type="salesforce",
        label="Salesforce",
        category="saas",
        description="Read standard and custom objects from Salesforce.",
        config_fields=(
            ConfigField(
                "instance",
                "Instance",
                placeholder="mycompany.my.salesforce.com",
                help="The domain your Salesforce org is served from.",
            ),
            ConfigField("auth_secret", "Access token", kind="secret"),
            ConfigField("page_size", "Page size", kind="number", required=False, default=200),
        ),
        capabilities=frozenset({"test", "discover", "read"}),
        documentation_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/",
    ),
    preset={
        "base_url": "https://{instance}/services/data/v59.0",
        "path": "/query",
        "records_path": "records",
        "auth_method": "bearer",
        "pagination": "none",
    },
    streams=_streams(
        ("Account", "/query?q=SELECT+FIELDS(STANDARD)+FROM+Account", "records"),
        ("Contact", "/query?q=SELECT+FIELDS(STANDARD)+FROM+Contact", "records"),
        ("Opportunity", "/query?q=SELECT+FIELDS(STANDARD)+FROM+Opportunity", "records"),
        ("Lead", "/query?q=SELECT+FIELDS(STANDARD)+FROM+Lead", "records"),
    ),
)

GOOGLE_SHEETS = PresetRestConnector(
    ConnectorSpec(
        type="google_sheets",
        label="Google Sheets",
        category="saas",
        description="Read a worksheet as a table.",
        config_fields=(
            ConfigField(
                "spreadsheet_id",
                "Spreadsheet id",
                help="The long id in the sheet's URL.",
            ),
            ConfigField("range", "Range", required=False, default="A1:ZZ", help="A1 notation."),
            ConfigField("auth_secret", "Access token", kind="secret"),
        ),
        capabilities=frozenset({"test", "read"}),
        documentation_url="https://developers.google.com/sheets/api",
    ),
    preset={
        "base_url": "https://sheets.googleapis.com/v4/spreadsheets",
        "path": "/{spreadsheet_id}/values/{range}",
        "records_path": "values",
        "auth_method": "bearer",
        "pagination": "none",
        "flatten": False,
    },
    streams=(),
)

SAAS_CONNECTORS = (STRIPE, HUBSPOT, SHOPIFY, SALESFORCE, GOOGLE_SHEETS)
