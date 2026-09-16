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
    PageParams,
    RestConnector,
    extract_records,
    merge_query,
    next_page_request,
    resolve_next_url,
    retry_delay_seconds,
)
from service_connectors.protocol import ConnectorError, StreamRef

TOTAL_RECORDS = 25
PAGE_SIZE = 10


class _Handler(BaseHTTPRequestHandler):
    """A small API: paginated, authenticated, and rate limiting on demand."""

    rate_limit_once = False
    seen_headers: dict[str, str] = {}
    seen_query: dict[str, list[str]] = {}

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
        type(self).seen_query = query

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


# ---- pagination vocabulary ----
#
# Every API paginates with the same four ideas and a different name for each.
# A name that is declared and then ignored is worse than no declaration: the
# request goes out without the parameter, the API answers with page one, and
# the loop collects the same rows until it gives up.


def test_a_page_strategy_uses_the_names_it_was_given():
    request = next_page_request(
        strategy="page",
        page_index=1,
        page_size=50,
        payload=None,
        headers={},
        cursor_path=None,
        names=PageParams(page="p", size="size"),
    )
    assert request == {"p": 2, "size": 50}


def test_a_page_strategy_can_count_from_zero():
    first = next_page_request(
        strategy="page",
        page_index=0,
        page_size=25,
        payload=None,
        headers={},
        cursor_path=None,
        names=PageParams(start_page=0),
    )
    assert first == {"page": 0, "per_page": 25}


def test_an_unnamed_size_follows_the_strategy_s_convention():
    """`per_page` beside a page number, `limit` beside an offset."""
    paged = next_page_request(
        strategy="page", page_index=0, page_size=10,
        payload=None, headers={}, cursor_path=None, names=PageParams(),
    )
    offset = next_page_request(
        strategy="offset", page_index=1, page_size=10,
        payload=None, headers={}, cursor_path=None, names=PageParams(),
    )
    assert paged == {"page": 1, "per_page": 10}
    assert offset == {"offset": 10, "limit": 10}


def test_a_cursor_goes_under_the_name_the_vendor_uses():
    request = next_page_request(
        strategy="cursor",
        page_index=1,
        page_size=100,
        payload={"meta": {"next": "abc"}},
        headers={},
        cursor_path="meta.next",
        names=PageParams(cursor="pageToken"),
    )
    assert request == {"pageToken": "abc"}


def test_an_api_that_rejects_a_size_parameter_is_not_sent_one():
    request = next_page_request(
        strategy="page", page_index=0, page_size=100,
        payload=None, headers={}, cursor_path=None,
        names=PageParams(send_size=False),
    )
    assert request == {"page": 1}


def test_the_names_are_read_off_a_connection_config():
    names = PageParams.from_config(
        {"page_param": "p", "cursor_param": "pageToken", "start_page": 0}
    )
    assert (names.page, names.cursor, names.start_page) == ("p", "pageToken", 0)
    # An unset size stays unset rather than becoming the string "None", so the
    # per-strategy convention still applies.
    assert names.size is None


def test_a_configured_cursor_name_reaches_the_wire(server: str):
    """The end-to-end version: the first request carries the renamed cursor."""
    RestConnector().read(
        {
            "base_url": server,
            "path": "/items",
            "records_path": "data.items",
            "pagination": "cursor",
            "cursor_param": "page_token",
        },
        cursor="opaque-token",
        limit=1,
    )
    assert _Handler.seen_query.get("page_token") == ["opaque-token"]


# ---- following a next-page address ----
#
# The token travels in an `Authorization` header, and httpx sends the headers it
# was constructed with to whatever host it is asked for. So a response saying
# "the next page is over there" is a request to hand a credential to `there`.


def test_a_same_origin_next_page_is_followed():
    assert (
        resolve_next_url("https://api.vendor.com/v2", "https://api.vendor.com/v2/x?page=2")
        == "https://api.vendor.com/v2/x?page=2"
    )


def test_a_relative_next_page_resolves_against_the_configured_base():
    """Confluence and Recurly both answer with a path rather than a URL."""
    assert (
        resolve_next_url("https://api.vendor.com/v2", "/wiki/api/v2/pages?cursor=abc")
        == "https://api.vendor.com/wiki/api/v2/pages?cursor=abc"
    )


def test_the_case_of_the_host_does_not_make_it_a_different_one():
    assert resolve_next_url("https://API.Vendor.com/v2", "https://api.vendor.com/v2/x")


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example/collect",
        "//evil.example/collect",          # protocol-relative: a different host
        "http://api.vendor.com/v2/x",      # downgraded to plaintext
        "https://api.vendor.com:8443/x",   # a different port is a different service
        "https://api.vendor.com.evil.example/x",
    ],
)
def test_a_next_page_somewhere_else_is_refused(hostile: str):
    from service_connectors.protocol import ConnectorError

    with pytest.raises(ConnectorError, match="not"):
        resolve_next_url("https://api.vendor.com/v2", hostile)


def test_merging_params_keeps_the_query_the_server_built():
    """httpx replaces a URL's query with `params=`, so it is merged in instead."""
    merged = merge_query("https://h/x?page=2&state=all", {"api_key": "k"})
    assert "page=2" in merged and "state=all" in merged and "api_key=k" in merged


def test_merging_never_overwrites_what_is_already_there():
    assert merge_query("https://h/x?api_key=theirs", {"api_key": "ours"}).count("api_key") == 1
