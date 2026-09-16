"""API *protocols*, as opposed to API vendors.

The manifest generator answers "how does Klaviyo paginate". These two answer a
different question: some APIs are not bespoke at all. OData and JSON:API each
specify the envelope, the paging and the error shape, so one connector reads
every service that implements them -- every Dynamics 365, Business Central, SAP
Gateway or SharePoint feed for OData; every Ember/Rails/Drupal API for JSON:API.

That is a better kind of leverage than another manifest. A manifest covers one
vendor; a protocol covers everyone who agreed to a standard, including the
internal service nobody here has heard of.

Both are the tested REST client with the standard's answers filled in, and both
are exercised end to end in `test_protocol_connectors.py` against a server that
answers the way the specification says -- which is what earns them tier 2 while
most of the catalogue stays at 4.
"""

from __future__ import annotations

from typing import Any

from service_connectors.adapters.rest import AUTH_METHODS, RestConnector
from service_connectors.protocol import (
    ConfigField,
    ConnectorError,
    ConnectorSpec,
    ReadResult,
    StreamColumn,
    StreamRef,
    TestResult,
    Tier,
    with_tier_note,
)

#: The credential settings both protocols share. Neither standard says anything
#: about authentication, so this is the REST connector's own vocabulary.
_AUTH_FIELDS = (
    ConfigField(
        "auth_method",
        "Authentication",
        kind="select",
        required=False,
        options=AUTH_METHODS,
        default="none",
    ),
    ConfigField("auth_username", "Username", required=False, help="Basic auth only."),
    ConfigField("auth_secret", "Token or key", kind="secret", required=False),
    ConfigField("auth_header_name", "Header name", required=False, default="X-API-Key"),
    ConfigField("auth_query_name", "Query parameter", required=False, default="api_key"),
)


class ODataConnector(RestConnector):
    """An OData v4 service.

    The standard supplies every answer this connector would otherwise have to
    guess: records live under `value`, server-driven paging hands back an
    absolute `@odata.nextLink`, client-driven paging is `$top` and `$skip`, and
    the service root lists its own entity sets. So `discover` really discovers,
    rather than returning a list somebody typed.
    """

    spec = ConnectorSpec(
        type="odata",
        label="OData",
        category="api",
        description=(
            "Read any OData v4 service -- Dynamics 365, Business Central, SAP Gateway, "
            "SharePoint -- by its service root."
        ),
        config_fields=(
            ConfigField(
                "base_url",
                "Service root",
                placeholder="https://host/api/data/v9.2",
                help="The URL whose response lists the entity sets.",
            ),
            ConfigField(
                "entity_set",
                "Entity set",
                required=False,
                help="Which collection to read. Discovery lists what is available.",
            ),
            ConfigField(
                "select",
                "$select",
                required=False,
                help="Comma-separated columns. Narrowing at the source beats dropping them here.",
            ),
            ConfigField(
                "filter",
                "$filter",
                required=False,
                placeholder="Status eq 'active'",
            ),
            ConfigField("page_size", "Page size", kind="number", required=False, default=100),
            *_AUTH_FIELDS,
        ),
        capabilities=frozenset({"test", "discover", "schema", "read"}),
        documentation_url="https://www.odata.org/documentation/",
        tier=Tier.CONTAINER,
        verified_by="test_protocol_connectors.py",
    )

    #: The entity set is a path segment, so it cannot be a place to build a URL.
    _UNSAFE_IN_PATH = frozenset('/\\?#@:%" \t\n\r')

    def _resolved(self, config: dict[str, Any], stream: StreamRef | None = None) -> dict[str, Any]:
        params: dict[str, str] = {}
        if config.get("select"):
            params["$select"] = str(config["select"])
        if config.get("filter"):
            params["$filter"] = str(config["filter"])

        return {
            **config,
            "path": f"/{self._entity_set(config, stream)}",
            "records_path": "value",
            # `$skip` beside `$top`: the client-driven half of the standard.
            # Server-driven paging wins when the service offers it, because
            # `next_url` is checked before the page counter advances.
            "pagination": "next_url",
            "cursor_path": "@odata.nextLink",
            "extra_params": params,
        }

    def _entity_set(self, config: dict[str, Any], stream: StreamRef | None) -> str:
        name = (stream.name if stream is not None else None) or config.get("entity_set")
        if not name:
            raise ConnectorError(
                "Name an entity set, or run discovery to see what this service offers."
            )
        text = str(name).strip().lstrip("/")
        offending = sorted(self._UNSAFE_IN_PATH & set(text))
        if offending:
            raise ConnectorError(
                f"An entity set cannot contain {' '.join(repr(c) for c in offending)}."
            )
        return text

    def test(self, config: dict[str, Any]) -> TestResult:
        """Read the service document, which is the one request every service answers."""
        import time

        started = time.perf_counter()
        try:
            with self._client(config) as client:
                response = client.get("/", params=self._auth_params(config))
        except Exception as exc:  # noqa: BLE001 - any transport failure is a failed test
            return TestResult(success=False, message=f"Could not reach the service: {exc}")

        latency = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code >= 400:
            return TestResult(
                success=False,
                message=f"The service answered {response.status_code} for its service root.",
                latency_ms=latency,
            )
        try:
            sets = self._entity_sets(response.json())
        except ValueError:
            return TestResult(
                success=False,
                message="The service root answered, but not with JSON.",
                latency_ms=latency,
            )
        return with_tier_note(
            TestResult(
                success=True,
                message=f"Connected. {len(sets)} entity set(s) published.",
                latency_ms=latency,
                server_version=response.headers.get("odata-version"),
                warnings=[] if sets else ["The service root lists no entity sets."],
            ),
            self.spec,
        )

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        with self._client(config) as client:
            response = client.get("/", params=self._auth_params(config))
        if response.status_code >= 400:
            raise ConnectorError(
                f"The service answered {response.status_code} for its service root."
            )
        return [
            StreamRef(name=name, kind="entity_set", detail={"url": url})
            for name, url in self._entity_sets(response.json())
        ]

    def columns(self, config: dict[str, Any], stream: StreamRef) -> list[StreamColumn]:
        """From one page, because OData describes types in a separate metadata
        document whose XML schema language is a project of its own.

        A sample is named as a sample rather than presented as the contract:
        `read` returns the same columns, and a field absent from the first page
        is absent here too.
        """
        result = self.read(config, stream, limit=1)
        frame = result.dataframe
        return [
            StreamColumn(name=str(name), data_type=_pandas_type(frame[name].dtype))
            for name in frame.columns
        ]

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef | None = None,
        *,
        limit: int = 10_000,
        cursor: str | None = None,
    ) -> ReadResult:
        return super().read(self._resolved(config, stream), None, limit=limit)

    # ------------------------------------------------------------- private

    def _auth_params(self, config: dict[str, Any]) -> dict[str, str]:
        from service_connectors.adapters.rest import _auth_query_params

        return _auth_query_params(config)

    @staticmethod
    def _entity_sets(document: Any) -> list[tuple[str, str]]:
        """The service document's collections, ignoring singletons and functions."""
        if not isinstance(document, dict):
            return []
        found: list[tuple[str, str]] = []
        for entry in document.get("value") or []:
            if not isinstance(entry, dict):
                continue
            # `kind` is omitted for entity sets, which is the standard's way of
            # saying "this is the usual case". Anything explicitly another kind
            # is not a collection of rows.
            if entry.get("kind") not in (None, "", "EntitySet"):
                continue
            name = str(entry.get("name") or entry.get("url") or "").strip()
            if name:
                found.append((name, str(entry.get("url") or name)))
        return found


class JsonApiConnector(RestConnector):
    """A JSON:API service.

    The standard puts the rows under `data`, the next page under `links.next`,
    and every field of a record inside `attributes` -- which is correct for a
    document format and useless as a table, so `attributes` is lifted to the top
    level alongside `id` and `type`. Relationships are left alone: flattening
    them would either multiply rows or invent columns whose count depends on the
    sample, and both change what a row means.
    """

    spec = ConnectorSpec(
        type="jsonapi",
        label="JSON:API",
        category="api",
        description=(
            "Read any service that implements the JSON:API specification, with "
            "attributes lifted into columns."
        ),
        config_fields=(
            ConfigField("base_url", "Base URL", placeholder="https://api.example.com"),
            ConfigField(
                "resource",
                "Resource type",
                required=False,
                placeholder="articles",
                help="The collection to read, e.g. 'articles'.",
            ),
            ConfigField(
                "include",
                "include",
                required=False,
                help="Related resources to fetch alongside. Returned as JSON, not columns.",
            ),
            ConfigField(
                "sparse_fields",
                "fields[type]",
                required=False,
                help="Comma-separated attribute names, if the service supports sparse fieldsets.",
            ),
            ConfigField("page_size", "Page size", kind="number", required=False, default=100),
            *_AUTH_FIELDS,
        ),
        capabilities=frozenset({"test", "schema", "read"}),
        documentation_url="https://jsonapi.org/format/",
        tier=Tier.CONTAINER,
        verified_by="test_protocol_connectors.py",
    )

    MEDIA_TYPE = "application/vnd.api+json"

    def _resolved(self, config: dict[str, Any], stream: StreamRef | None = None) -> dict[str, Any]:
        resource = (stream.name if stream is not None else None) or config.get("resource")
        if not resource:
            raise ConnectorError("Name the resource type to read, e.g. 'articles'.")
        text = str(resource).strip().lstrip("/")
        if set('/\\?#@:%" \t\n\r') & set(text):
            raise ConnectorError("A resource type is a path segment, not a URL.")

        params: dict[str, str] = {}
        if config.get("include"):
            params["include"] = str(config["include"])
        if config.get("sparse_fields"):
            params[f"fields[{text}]"] = str(config["sparse_fields"])
        # The standard names the page family but leaves the strategy to the
        # service; offset is the one every implementation supports.
        return {
            **config,
            "path": f"/{text}",
            "records_path": "data",
            "pagination": "next_url",
            "cursor_path": "links.next",
            "offset_param": "page[offset]",
            "size_param": "page[limit]",
            "extra_headers": {
                **(config.get("extra_headers") or {}),
                "Accept": self.MEDIA_TYPE,
            },
            "extra_params": params,
            # The lifting below is this connector's job; the generic flattener
            # would produce `attributes.title` and leave every column prefixed.
            "flatten": False,
        }

    def test(self, config: dict[str, Any]) -> TestResult:
        return with_tier_note(super().test(self._resolved(config)), self.spec)

    def columns(self, config: dict[str, Any], stream: StreamRef) -> list[StreamColumn]:
        frame = self.read(config, stream, limit=1).dataframe
        return [
            StreamColumn(
                name=str(name),
                data_type=_pandas_type(frame[name].dtype),
                primary_key=name == "id",
            )
            for name in frame.columns
        ]

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef | None = None,
        *,
        limit: int = 10_000,
        cursor: str | None = None,
    ) -> ReadResult:
        import pandas as pd

        result = super().read(self._resolved(config, stream), None, limit=limit)
        records = result.dataframe.to_dict("records") if len(result.dataframe) else []
        result.dataframe = pd.DataFrame([_lift(record) for record in records])
        result.row_count = len(result.dataframe)
        return result


def _lift(record: dict[str, Any]) -> dict[str, Any]:
    """`{id, type, attributes: {...}}` as one row.

    An attribute called `id` or `type` does not overwrite the resource's own --
    the identifier is what makes the row addressable, and losing it silently
    would be worse than a slightly awkward column name.
    """
    from service_connectors.flatten import flatten_document

    row: dict[str, Any] = {}
    identity = {"id": record.get("id"), "type": record.get("type")}
    attributes = record.get("attributes")
    if isinstance(attributes, dict):
        row.update(flatten_document(attributes))
    for key, value in record.items():
        if key in ("id", "type", "attributes"):
            continue
        row[key] = value if isinstance(value, (str, int, float, bool, type(None))) else _json(value)
    for key, value in identity.items():
        if key in row:
            row[f"resource_{key}"] = value
        else:
            row[key] = value
    return row


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


def _pandas_type(dtype: Any) -> str:
    name = str(dtype)
    if name.startswith(("int", "Int")):
        return "integer"
    if name.startswith(("float", "Float")):
        return "float"
    if name.startswith(("bool", "boolean")):
        return "boolean"
    if "datetime" in name:
        return "timestamp"
    return "string"


PROTOCOL_CONNECTORS = (ODataConnector(), JsonApiConnector())
