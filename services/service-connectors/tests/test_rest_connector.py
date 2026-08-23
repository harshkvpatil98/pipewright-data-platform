"""The REST connector, against a real HTTP server.

Mocking httpx would test that the mock was configured correctly. A server on a
loopback port tests pagination, rate limiting, and auth headers the way they
actually behave -- which is where connectors go wrong.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from service_connectors.adapters.rest import (
    GraphQlConnector,
    RestConnector,
    extract_records,
    next_page_request,
    retry_delay_seconds,
)
from service_connectors.protocol import ConnectorError, StreamRef

TOTAL_RECORDS = 25
PAGE_SIZE = 10


class _Handler(BaseHTTPRequestHandler):
    """A small API: paginated, authenticated, and rate limiting on demand."""

    rate_limit_once = False
    seen_headers: dict[str, str] = {}

    def log_message(self, *_args):  # noqa: D102 - silence the test output
        return

    def _json(self, status: int, payload: object, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - the stdlib's naming
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        type(self).seen_headers = dict(self.headers)

        if parsed.path == "/secure" and self.headers.get("Authorization") != "Bearer s3cret":
            self._json(401, {"error": "unauthorised"})
            return

        if parsed.path == "/flaky" and type(self).rate_limit_once:
            type(self).rate_limit_once = False
            self._json(429, {"error": "slow down"}, {"Retry-After": "0"})
            return

        page = int(query.get("page", ["1"])[0])
        size = int(query.get("per_page", [str(PAGE_SIZE)])[0])
        start = (page - 1) * size
        records = [
            {"id": index, "name": f"row-{index}", "nested": {"score": index * 2}}
            for index in range(start, min(start + size, TOTAL_RECORDS))
        ]
        self._json(200, {"data": {"items": records}, "total": TOTAL_RECORDS})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self._json(200, {"data": {"orders": [{"id": 1, "total": 9.99}]}})


class _FastHTTPServer(HTTPServer):
    """An HTTPServer that binds immediately.

    `HTTPServer.server_bind` calls `socket.getfqdn()` to fill in `server_name`,
    which on a machine with no reverse DNS for its loopback address blocks for
    the full resolver timeout -- about 35 seconds, once, at fixture setup. The
    value is only used to populate a header nothing here reads.
    """

    def server_bind(self):
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


# ---- pure helpers ----


def test_records_are_found_down_a_dotted_path():
    payload = {"data": {"items": [{"id": 1}, {"id": 2}]}}
    assert extract_records(payload, "data.items") == [{"id": 1}, {"id": 2}]


def test_a_bare_array_response_needs_no_path():
    assert extract_records([{"id": 1}], None) == [{"id": 1}]


def test_a_single_object_is_wrapped_rather_than_rejected():
    assert extract_records({"id": 1}, None) == [{"id": 1}]


def test_a_wrong_path_says_what_was_actually_there():
    with pytest.raises(ConnectorError) as caught:
        extract_records({"results": []}, "data.items")
    assert "results" in caught.value.message


def test_page_and_offset_pagination_ask_for_the_right_next_batch():
    assert next_page_request(
        strategy="page", page_index=2, page_size=50, payload=None, headers={}, cursor_path=None
    ) == {"page": 3, "per_page": 50}
    assert next_page_request(
        strategy="offset", page_index=2, page_size=50, payload=None, headers={}, cursor_path=None
    ) == {"offset": 100, "limit": 50}


def test_cursor_pagination_stops_when_the_token_runs_out():
    assert next_page_request(
        strategy="cursor",
        page_index=1,
        page_size=10,
        payload={"next_cursor": "abc"},
        headers={},
        cursor_path="next_cursor",
    ) == {"cursor": "abc"}
    assert (
        next_page_request(
            strategy="cursor",
            page_index=1,
            page_size=10,
            payload={"next_cursor": None},
            headers={},
            cursor_path="next_cursor",
        )
        is None
    )


def test_link_header_pagination_follows_the_next_relation():
    headers = {"link": '<https://api/x?page=2>; rel="next", <https://api/x?page=9>; rel="last"'}
    assert next_page_request(
        strategy="link_header",
        page_index=1,
        page_size=10,
        payload=None,
        headers=headers,
        cursor_path=None,
    ) == {"__url__": "https://api/x?page=2"}


def test_the_servers_own_retry_after_wins_over_backoff():
    assert retry_delay_seconds({"retry-after": "5"}, attempt=3) == 5.0
    assert retry_delay_seconds({}, attempt=3) == 8.0


def test_an_absurd_retry_after_is_capped():
    """An hour-long sleep inside a run is indistinguishable from a hang."""
    assert retry_delay_seconds({"retry-after": "99999"}, attempt=0) == 60


# ---- against the server ----


def test_test_reports_what_it_found(server: str):
    result = RestConnector().test(
        {"base_url": server, "path": "/items", "records_path": "data.items"}
    )
    assert result.success
    assert "record(s)" in result.message
    assert result.latency_ms is not None


def test_a_wrong_records_path_fails_the_test_rather_than_the_run(server: str):
    result = RestConnector().test(
        {"base_url": server, "path": "/items", "records_path": "nope"}
    )
    assert result.success is False
    assert "nope" in result.message


def test_an_unreachable_host_is_a_failed_test_not_an_exception():
    result = RestConnector().test({"base_url": "http://127.0.0.1:1", "path": "/"})
    assert result.success is False
    assert "Could not reach" in result.message


def test_reading_follows_pagination_to_the_end(server: str):
    """The classic failure: taking page one and never noticing the rest."""
    result = RestConnector().read(
        {
            "base_url": server,
            "path": "/items",
            "records_path": "data.items",
            "pagination": "page",
            "page_size": PAGE_SIZE,
        }
    )
    assert result.row_count == TOTAL_RECORDS
    assert result.truncated is False


def test_nested_fields_arrive_as_dotted_columns(server: str):
    result = RestConnector().read(
        {"base_url": server, "path": "/items", "records_path": "data.items"}
    )
    assert "nested.score" in result.dataframe.columns


def test_flattening_can_be_turned_off(server: str):
    result = RestConnector().read(
        {
            "base_url": server,
            "path": "/items",
            "records_path": "data.items",
            "flatten": False,
        }
    )
    assert "nested" in result.dataframe.columns
    assert "nested.score" not in result.dataframe.columns


def test_the_row_limit_is_honoured_and_reported(server: str):
    result = RestConnector().read(
        {
            "base_url": server,
            "path": "/items",
            "records_path": "data.items",
            "pagination": "page",
            "page_size": PAGE_SIZE,
        },
        limit=12,
    )
    assert result.row_count == 12
    assert result.truncated is True


def test_a_bearer_token_reaches_the_server(server: str):
    result = RestConnector().test(
        {
            "base_url": server,
            "path": "/secure",
            "records_path": "data.items",
            "auth_method": "bearer",
            "auth_secret": "s3cret",
        }
    )
    assert result.success


def test_a_missing_token_is_reported_as_the_status_the_api_gave(server: str):
    result = RestConnector().test({"base_url": server, "path": "/secure"})
    assert result.success is False
    assert "401" in result.message


def test_an_api_key_header_is_sent_under_the_configured_name(server: str):
    RestConnector().test(
        {
            "base_url": server,
            "path": "/items",
            "records_path": "data.items",
            "auth_method": "api_key_header",
            "auth_header_name": "X-Custom-Key",
            "auth_secret": "abc123",
        }
    )
    assert _Handler.seen_headers.get("X-Custom-Key") == "abc123"


def test_a_rate_limit_is_waited_out_rather_than_hammered(server: str):
    _Handler.rate_limit_once = True
    result = RestConnector().read(
        {"base_url": server, "path": "/flaky", "records_path": "data.items"}
    )
    assert result.row_count > 0


def test_graphql_runs_one_post_and_reads_the_result(server: str):
    result = GraphQlConnector().read(
        {
            "base_url": f"{server}/graphql",
            "query": "{ orders { id total } }",
            "records_path": "data.orders",
        }
    )
    assert result.row_count == 1
    assert list(result.dataframe.columns) == ["id", "total"]


def test_a_stream_overrides_the_configured_path(server: str):
    result = RestConnector().read(
        {"base_url": server, "path": "/unused", "records_path": "data.items"},
        StreamRef(name="/items"),
        limit=3,
    )
    assert result.row_count == 3
