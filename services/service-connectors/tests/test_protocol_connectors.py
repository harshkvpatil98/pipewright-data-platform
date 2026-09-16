"""OData and JSON:API, against servers that answer the way the standards say.

These two are worth more than a manifest each: a manifest covers one vendor,
and a protocol covers everybody who implemented the specification -- including
the internal service nobody here has heard of. That makes it worth testing them
properly rather than trusting that "it is just REST underneath".

The fixtures are built from the published specifications: OData's service
document and `@odata.nextLink`, JSON:API's `data`/`attributes`/`links.next`.
They are what makes `tier=2` an honest claim for both.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

import service_connectors  # noqa: F401  -- assembles the catalogue
from service_connectors.adapters.protocols import JsonApiConnector, ODataConnector, _lift
from service_connectors.protocol import ConnectorError, StreamRef

PAGE = 3


class _Handler(BaseHTTPRequestHandler):
    """One server, two standards, dispatching on the path."""

    seen: list[dict[str, Any]] = []

    def log_message(self, *_args: Any) -> None:
        return

    def _send(self, status: int, payload: Any, content_type: str) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("OData-Version", "4.0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's naming
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        type(self).seen.append(
            {"path": parsed.path, "query": query, "headers": dict(self.headers)}
        )
        root = f"http://127.0.0.1:{self.server.server_port}"

        # --- OData ---------------------------------------------------------
        if parsed.path in ("/odata", "/odata/"):
            self._send(
                200,
                {
                    "@odata.context": f"{root}/odata/$metadata",
                    "value": [
                        {"name": "Products", "kind": "EntitySet", "url": "Products"},
                        {"name": "Customers", "url": "Customers"},
                        {"name": "Me", "kind": "Singleton", "url": "Me"},
                        {"name": "Reset", "kind": "FunctionImport", "url": "Reset"},
                    ],
                },
                "application/json",
            )
            return

        if parsed.path == "/odata/Products":
            second = query.get("$skiptoken") == ["p2"]
            body: dict[str, Any] = {
                "@odata.context": f"{root}/odata/$metadata#Products",
                "value": [
                    {"Id": index, "Name": f"widget-{index}", "Price": 1.5 * index}
                    for index in (range(PAGE, PAGE * 2) if second else range(PAGE))
                ],
            }
            if not second:
                # Server-driven paging: an absolute URL, exactly as the
                # specification describes it.
                body["@odata.nextLink"] = f"{root}/odata/Products?$skiptoken=p2"
            self._send(200, body, "application/json")
            return

        if parsed.path == "/odata/Empty":
            self._send(200, {"value": []}, "application/json")
            return

        # --- JSON:API ------------------------------------------------------
        if parsed.path == "/jsonapi/articles":
            offset = int((query.get("page[offset]") or ["0"])[0])
            second = offset > 0 or query.get("cursor") == ["2"]
            data = [
                {
                    "type": "articles",
                    "id": str(index),
                    "attributes": {
                        "title": f"post-{index}",
                        "wordCount": index * 100,
                        "author": {"name": f"writer-{index}"},
                    },
                    "relationships": {"comments": {"data": [{"type": "comments", "id": "9"}]}},
                }
                for index in (range(PAGE, PAGE * 2) if second else range(PAGE))
            ]
            payload: dict[str, Any] = {"data": data, "links": {"self": self.path}}
            if not second:
                payload["links"]["next"] = f"{root}/jsonapi/articles?page[offset]={PAGE}"
            self._send(200, payload, JsonApiConnector.MEDIA_TYPE)
            return

        if parsed.path == "/jsonapi/collisions":
            self._send(
                200,
                {
                    "data": [
                        {
                            "type": "things",
                            "id": "42",
                            "attributes": {"id": "inner", "type": "inner-type", "ok": True},
                        }
                    ],
                    "links": {"self": self.path},
                },
                JsonApiConnector.MEDIA_TYPE,
            )
            return

        self._send(404, {"error": "no such path"}, "application/json")


class _FastHTTPServer(HTTPServer):
    """Binds without waiting on `socket.getfqdn()`, which blocks ~35s on macOS."""

    def server_bind(self) -> None:
        import socketserver

        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = _FastHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(autouse=True)
def _clear() -> Iterator[None]:
    _Handler.seen = []
    yield


class TestOData:
    def _config(self, server: str, **overrides: Any) -> dict[str, Any]:
        return {"base_url": f"{server}/odata", "entity_set": "Products", **overrides}

    def test_the_service_document_is_the_connection_test(self, server: str) -> None:
        result = ODataConnector().test(self._config(server))
        assert result.success, result.message
        assert "2 entity set(s)" in result.message
        assert result.server_version == "4.0"

    def test_discovery_reads_the_service_s_own_list(self, server: str) -> None:
        """Genuinely discovered, not a list somebody typed into a manifest."""
        streams = ODataConnector().discover(self._config(server))
        assert [stream.name for stream in streams] == ["Products", "Customers"]

    def test_a_singleton_and_a_function_are_not_collections(self, server: str) -> None:
        names = {stream.name for stream in ODataConnector().discover(self._config(server))}
        assert "Me" not in names and "Reset" not in names

    def test_it_reads_rows_from_the_value_array(self, server: str) -> None:
        result = ODataConnector().read(self._config(server), StreamRef(name="Products"))
        assert sorted(result.dataframe.columns) == ["Id", "Name", "Price"]
        assert result.row_count == PAGE * 2

    def test_it_follows_the_server_s_next_link(self, server: str) -> None:
        """`@odata.nextLink` is one key containing a dot.

        Splitting it on the dot finds nothing, which reads as "there is no next
        page" -- a silent half-read that a row count never reveals.
        """
        ODataConnector().read(self._config(server), StreamRef(name="Products"))
        reads = [entry for entry in _Handler.seen if entry["path"] == "/odata/Products"]
        assert len(reads) == 2
        assert reads[1]["query"]["$skiptoken"] == ["p2"]

    def test_select_and_filter_reach_the_service(self, server: str) -> None:
        """Narrowing at the source is the whole reason these settings exist."""
        ODataConnector().read(
            self._config(server, select="Id,Name", filter="Price gt 1"),
            StreamRef(name="Products"),
        )
        first = _Handler.seen[0]["query"]
        assert first["$select"] == ["Id,Name"]
        assert first["$filter"] == ["Price gt 1"]

    def test_the_columns_come_from_a_page(self, server: str) -> None:
        columns = ODataConnector().columns(self._config(server), StreamRef(name="Products"))
        by_name = {column.name: column.data_type for column in columns}
        assert by_name["Id"] == "integer"
        assert by_name["Price"] == "float"
        assert by_name["Name"] == "string"

    def test_an_empty_collection_is_not_an_error(self, server: str) -> None:
        result = ODataConnector().read(self._config(server), StreamRef(name="Empty"))
        assert result.row_count == 0

    def test_an_entity_set_cannot_be_a_url(self, server: str) -> None:
        """A path segment is a piece of a URL, never a place to build one."""
        with pytest.raises(ConnectorError, match="cannot contain"):
            ODataConnector().read(
                self._config(server), StreamRef(name="Products?x=1&y=../../admin")
            )

    def test_naming_nothing_asks_rather_than_guessing(self, server: str) -> None:
        with pytest.raises(ConnectorError, match="Name an entity set"):
            ODataConnector().read({"base_url": f"{server}/odata"})

    def test_a_verified_read_carries_no_tier_caveat(self, server: str) -> None:
        result = ODataConnector().read(self._config(server), StreamRef(name="Products"))
        assert not any("unverified" in warning.lower() for warning in result.warnings)


class TestJsonApi:
    def _config(self, server: str, **overrides: Any) -> dict[str, Any]:
        return {"base_url": f"{server}/jsonapi", "resource": "articles", **overrides}

    def test_it_asks_for_the_media_type_the_standard_defines(self, server: str) -> None:
        JsonApiConnector().read(self._config(server))
        assert _Handler.seen[0]["headers"]["Accept"] == JsonApiConnector.MEDIA_TYPE

    def test_attributes_become_columns(self, server: str) -> None:
        """`attributes.title` is correct for a document and useless as a table."""
        result = JsonApiConnector().read(self._config(server))
        assert "title" in result.dataframe.columns
        assert "attributes.title" not in result.dataframe.columns
        assert set(result.dataframe.columns) >= {"id", "type", "title", "wordCount"}

    def test_a_nested_attribute_keeps_its_path(self, server: str) -> None:
        result = JsonApiConnector().read(self._config(server))
        assert "author.name" in result.dataframe.columns

    def test_relationships_are_kept_as_json_rather_than_exploded(self, server: str) -> None:
        """Exploding them multiplies rows or invents sample-dependent columns."""
        result = JsonApiConnector().read(self._config(server))
        assert "relationships" in result.dataframe.columns
        assert "comments" in str(result.dataframe["relationships"].iloc[0])

    def test_it_follows_links_next(self, server: str) -> None:
        result = JsonApiConnector().read(self._config(server))
        assert result.row_count == PAGE * 2
        assert len(_Handler.seen) == 2
        assert _Handler.seen[1]["query"]["page[offset]"] == [str(PAGE)]

    def test_an_include_and_a_sparse_fieldset_reach_the_service(self, server: str) -> None:
        JsonApiConnector().read(self._config(server, include="author", sparse_fields="title"))
        query = _Handler.seen[0]["query"]
        assert query["include"] == ["author"]
        assert query["fields[articles]"] == ["title"]

    def test_the_identifier_survives_an_attribute_of_the_same_name(self) -> None:
        """Losing the id silently would be worse than an awkward column name."""
        row = _lift(
            {"type": "things", "id": "42", "attributes": {"id": "inner", "type": "inner-type"}}
        )
        assert row["id"] == "inner"
        assert row["resource_id"] == "42"
        assert row["resource_type"] == "things"

    def test_that_collision_survives_a_real_response(self, server: str) -> None:
        result = JsonApiConnector().read(self._config(server, resource="collisions"))
        assert result.dataframe["resource_id"].iloc[0] == "42"
        assert result.dataframe["id"].iloc[0] == "inner"

    def test_the_columns_mark_the_identifier(self, server: str) -> None:
        columns = JsonApiConnector().columns(self._config(server), StreamRef(name="articles"))
        keys = [column.name for column in columns if column.primary_key]
        assert keys == ["id"]

    def test_a_resource_type_cannot_be_a_url(self, server: str) -> None:
        with pytest.raises(ConnectorError, match="path segment"):
            JsonApiConnector().read(self._config(server, resource="articles?x=1"))

    def test_naming_nothing_asks_rather_than_guessing(self, server: str) -> None:
        with pytest.raises(ConnectorError, match="Name the resource"):
            JsonApiConnector().read({"base_url": f"{server}/jsonapi"})


class TestBothAreInTheCatalogue:
    def test_they_are_registered_with_the_tier_this_file_backs(self) -> None:
        from service_connectors.registry import spec_for

        for key in ("odata", "jsonapi"):
            spec = spec_for(key)
            assert int(spec.tier) == 2
            assert spec.verified_by == "test_protocol_connectors.py"
            assert spec.category == "api"

    def test_they_pass_the_conformance_suite_unchanged(self) -> None:
        from service_connectors.conformance import check_spec
        from service_connectors.registry import get

        for key in ("odata", "jsonapi"):
            report = check_spec(get(key))
            assert report.ok, report.failures
