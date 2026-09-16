"""REST and GraphQL APIs.

The three things that make an API connector work in practice, and which a naive
`requests.get` in a loop gets wrong:

**Pagination.** Every API invented its own. Rather than one guess, the strategy
is declared -- page numbers, offsets, a cursor in the body, or a `Link` header --
and each is a few lines. Getting only the first hundred rows and never noticing
is the classic failure here.

**Rate limits.** A 429 with a `Retry-After` is the server asking politely; the
connector waits rather than hammering and getting blocked. Every other error is
returned as a failure, because retrying a 401 forever helps nobody.

**Extraction.** JSON is nested; a table is not. The path to the array of records
is configuration, and what comes out is flattened with the same code the NoSQL
connector uses, so `user.address.city` means the same thing in both.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from service_connectors.protocol import (
    ConfigField,
    ConnectorError,
    ConnectorSpec,
    ReadResult,
    StreamRef,
    TestResult,
    Tier,
    with_tier_note,
)

PAGINATION_STRATEGIES = ("none", "page", "offset", "cursor", "next_url", "link_header")
AUTH_METHODS = ("none", "bearer", "api_key_header", "api_key_query", "basic")

# A page loop with no ceiling is a way to hang a worker forever on an API that
# keeps returning a next-page token.
MAX_PAGES = 200
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRY_WAIT_SECONDS = 60


def _headers(config: dict[str, Any]) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    method = str(config.get("auth_method") or "none")
    secret = str(config.get("auth_secret") or "")

    # A manifest can supply the exact wording a vendor wants -- Klaviyo asks for
    # `Klaviyo-API-Key {token}`, Shopify for a bare token in its own header --
    # rather than this module carrying a special case per vendor.
    template = config.get("auth_template")
    if template and secret:
        headers[str(config.get("auth_header_name") or "Authorization")] = str(template).format(
            token=secret
        )
    elif method == "bearer" and secret:
        headers["Authorization"] = f"Bearer {secret}"
    elif method == "api_key_header" and secret:
        headers[str(config.get("auth_header_name") or "X-API-Key")] = secret
    elif method == "basic" and secret:
        import base64

        username = str(config.get("auth_username") or "")
        encoded = base64.b64encode(f"{username}:{secret}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    extra = config.get("extra_headers")
    if isinstance(extra, dict):
        headers.update({str(key): str(value) for key, value in extra.items()})
    return headers


def _auth_query_params(config: dict[str, Any]) -> dict[str, str]:
    """The credential, when this API wants it in the query string rather than a header."""
    if str(config.get("auth_method")) != "api_key_query":
        return {}
    name = str(config.get("auth_query_name") or "api_key")
    return {name: str(config.get("auth_secret") or "")}


def _query_params(config: dict[str, Any]) -> dict[str, str]:
    params: dict[str, str] = dict(_auth_query_params(config))
    # Fixed query parameters a stream always sends, and the incremental filter.
    # Supplied by a manifest; absent for a hand-configured REST connection.
    extra = config.get("extra_params")
    if isinstance(extra, dict):
        params.update({str(key): str(value) for key, value in extra.items() if value is not None})
    return params


def extract_records(payload: Any, records_path: str | None) -> list[dict[str, Any]]:
    """Find the array of records inside a response.

    An empty path means the response *is* the array. A dotted path walks into
    it. Anything else -- a single object, a number -- is wrapped rather than
    rejected, because plenty of APIs return one record without a list around it.
    """
    current = payload
    for part in (records_path or "").split("."):
        part = part.strip()
        if not part:
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ConnectorError(
                f"The response has no '{records_path}' in it. "
                f"Top-level keys: {', '.join(map(str, current))}"
                if isinstance(current, dict)
                else f"The response has no '{records_path}' in it."
            )

    if isinstance(current, list):
        return [item if isinstance(item, dict) else {"value": item} for item in current]
    if isinstance(current, dict):
        return [current]
    return [{"value": current}]


@dataclass(frozen=True)
class PageParams:
    """What this API calls its pagination parameters.

    Every API paginates with the same four ideas and a different vocabulary for
    them: `page`/`per_page`, `p`/`size`, `offset`/`limit`, `cursor`,
    `page[cursor]`, `starting_after`. Hard-coding one vocabulary and reading the
    others from a manifest that then gets ignored is worse than not reading them
    at all -- the request goes out without the parameter, the API answers with
    page one again, and the connector loops collecting the same rows until it
    hits `MAX_PAGES`. So the names travel with the strategy.
    """

    page: str = "page"
    #: None means "use the convention for this strategy" -- `per_page` beside a
    #: page number, `limit` beside an offset. Kept distinct from an explicit
    #: name so a manifest that says nothing still gets the right one.
    size: str | None = None
    offset: str = "offset"
    cursor: str = "cursor"
    #: The number the first page is called. Zero for the APIs that count from 0.
    start_page: int = 1
    #: False when the API rejects an unknown page-size parameter. Rare, but a
    #: 400 on the second page is a confusing way to find out.
    send_size: bool = True

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> PageParams:
        defaults = cls()
        size = config.get("size_param")
        return cls(
            page=str(config.get("page_param") or defaults.page),
            size=str(size) if size else None,
            offset=str(config.get("offset_param") or defaults.offset),
            cursor=str(config.get("cursor_param") or defaults.cursor),
            start_page=int(config.get("start_page", defaults.start_page)),
            send_size=bool(config.get("send_page_size", defaults.send_size)),
        )


def next_page_request(
    *,
    strategy: str,
    page_index: int,
    page_size: int,
    payload: Any,
    headers: dict[str, str],
    cursor_path: str | None,
    names: PageParams | None = None,
) -> dict[str, Any] | None:
    """The query parameters for the next page, or None when there is no next page."""
    names = names or PageParams()
    if strategy == "none":
        return None
    if strategy == "page":
        request: dict[str, Any] = {names.page: page_index + names.start_page}
        if names.send_size:
            request[names.size or "per_page"] = page_size
        return request
    if strategy == "offset":
        request = {names.offset: page_index * page_size}
        if names.send_size:
            request[names.size or "limit"] = page_size
        return request
    if strategy == "cursor":
        token = _walk(payload, cursor_path or "next_cursor")
        return {names.cursor: str(token)} if token else None
    if strategy == "next_url":
        # A large family of APIs -- Zendesk, Klaviyo, Bitbucket, Front, PostHog,
        # Confluence, Recurly -- put the *address* of the next page in the body
        # rather than a token to pass back. Sending that address as the value of
        # a cursor parameter asks for page one again with a very long argument,
        # which reads as "the API only has one page" for as long as nobody
        # counts the rows.
        target = _walk(payload, cursor_path or "next")
        if not isinstance(target, str) or not target.strip():
            return None
        return {"__url__": target.strip()}
    if strategy == "link_header":
        link = headers.get("link") or headers.get("Link") or ""
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                return {"__url__": url} if url else None
        return None
    raise ConnectorError(f"Unknown pagination strategy '{strategy}'.")


def merge_query(url: str, params: dict[str, str]) -> str:
    """Add parameters to a URL that already has its own query string.

    `httpx` treats `params=` as the whole query, not an addition to one, so a
    next-page address has to carry everything it needs before it is requested.
    """
    if not params:
        return url
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    existing = parse_qsl(parts.query, keep_blank_values=True)
    present = {name for name, _ in existing}
    merged = existing + [
        (name, value) for name, value in params.items() if name not in present
    ]
    return urlunsplit(parts._replace(query=urlencode(merged)))


def resolve_next_url(base_url: str, candidate: str) -> str:
    """The next page's address, refused unless the API is naming its own pages.

    The token travels in an `Authorization` header, and httpx sends the headers
    it was constructed with to whatever host it is asked for. So a response that
    says "the next page is at https://somewhere-else/collect" would hand that
    host the credential. Same-origin is the only safe reading of a next-page
    link, and a relative one -- which is what Confluence and Recurly return --
    resolves against the configured base.
    """
    from urllib.parse import urljoin, urlsplit

    base = urlsplit(base_url)
    target = urlsplit(candidate)
    if not target.scheme and not target.netloc:
        return urljoin(f"{base.scheme}://{base.netloc}", candidate)
    # Scheme and host are case-insensitive; the comparison has to be too, or a
    # service that answers with its own name in capitals looks like an attacker.
    here = (base.scheme.lower(), base.netloc.lower())
    there = (target.scheme.lower(), target.netloc.lower())
    if there != here:
        raise ConnectorError(
            f"The API said its next page is at {target.scheme}://{target.netloc}, "
            f"which is not {base.scheme}://{base.netloc}. Following that would send "
            "this connection's credential to a host the configuration never named."
        )
    return candidate


def _walk(payload: Any, path: str) -> Any:
    """Follow a dotted path into a response body.

    A literal key wins over splitting it. OData's next-page link is called
    `@odata.nextLink` -- one key with a dot in it -- and walking into `@odata`
    and then `nextLink` finds nothing, which reads as "there is no next page".
    """
    current = payload
    remaining = path
    while remaining:
        if not isinstance(current, dict):
            return None
        if remaining in current:
            return current[remaining]
        head, separator, remaining = remaining.partition(".")
        head = head.strip()
        if not head:
            if not separator:
                return current
            continue
        current = current.get(head)
        if not separator:
            return current
    return current


def retry_delay_seconds(headers: dict[str, str], attempt: int) -> float:
    """How long to wait after a rate limit.

    The server's own `Retry-After` wins; only when it says nothing does this
    back off on its own. Capped, because an hour-long sleep inside a run is
    indistinguishable from a hang.
    """
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw:
        try:
            return min(float(raw), MAX_RETRY_WAIT_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt, MAX_RETRY_WAIT_SECONDS)


class RestConnector:
    """A JSON API, read as a table."""

    spec = ConnectorSpec(
        type="rest_api",
        label="REST API",
        category="api",
        description="Read JSON from an HTTP API, following its pagination.",
        tier=Tier.CONTAINER,
        verified_by="test_rest_connector.py",
        config_fields=(
            ConfigField("base_url", "Base URL", placeholder="https://api.example.com"),
            ConfigField(
                "path",
                "Path",
                required=False,
                default="/",
                help="Appended to the base URL. This is the stream that gets read.",
            ),
            ConfigField(
                "records_path",
                "Records path",
                required=False,
                help="Where the array of records sits, e.g. 'data.items'. Blank if the response is the array.",
            ),
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
            ConfigField(
                "pagination",
                "Pagination",
                kind="select",
                required=False,
                options=PAGINATION_STRATEGIES,
                default="none",
            ),
            ConfigField("page_size", "Page size", kind="number", required=False, default=100),
            ConfigField(
                "cursor_path",
                "Cursor path",
                required=False,
                default="next_cursor",
                help="Where the next-page token sits in the response.",
            ),
            # What this API calls its pagination parameters. Offered because
            # the alternative is a connection that looks configured, requests
            # page one repeatedly, and reports a row count that is a multiple
            # of the page size.
            ConfigField(
                "page_param",
                "Page parameter",
                required=False,
                default="page",
                help="Page-number pagination only.",
            ),
            ConfigField(
                "size_param",
                "Page-size parameter",
                required=False,
                help="Blank uses this API's convention: per_page beside a page, limit beside an offset.",
            ),
            ConfigField(
                "offset_param",
                "Offset parameter",
                required=False,
                default="offset",
                help="Offset pagination only.",
            ),
            ConfigField(
                "cursor_param",
                "Cursor parameter",
                required=False,
                default="cursor",
                help="Cursor pagination only, e.g. pageToken or starting_after.",
            ),
            ConfigField(
                "start_page",
                "First page number",
                kind="number",
                required=False,
                default=1,
                help="Zero for the APIs that count pages from zero.",
            ),
            ConfigField(
                "flatten",
                "Flatten nested fields",
                kind="boolean",
                required=False,
                default=True,
                help="Turn user.address.city into a column of that name.",
            ),
        ),
        capabilities=frozenset({"test", "read"}),
    )

    def _client(self, config: dict[str, Any]):
        import httpx

        return httpx.Client(
            base_url=str(config["base_url"]).rstrip("/"),
            headers=_headers(config),
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    def test(self, config: dict[str, Any]) -> TestResult:
        started = time.perf_counter()
        try:
            with self._client(config) as client:
                response = client.get(
                    str(config.get("path") or "/"),
                    params={**_query_params(config), "limit": 1},
                )
        except Exception as exc:  # noqa: BLE001 - any transport failure is a failed test
            return TestResult(success=False, message=f"Could not reach the API: {exc}")

        latency = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code >= 400:
            return TestResult(
                success=False,
                message=f"The API answered {response.status_code}.",
                latency_ms=latency,
            )

        warnings: list[str] = []
        try:
            payload = response.json()
        except ValueError:
            return TestResult(
                success=False,
                message="The API answered, but not with JSON.",
                latency_ms=latency,
            )

        try:
            records = extract_records(payload, config.get("records_path"))
        except ConnectorError as exc:
            return TestResult(success=False, message=exc.message, latency_ms=latency)

        if not records:
            warnings.append("The API answered, but returned no records.")

        return with_tier_note(
            TestResult(
                success=True,
                message=f"Connected. {len(records)} record(s) in the first response.",
                latency_ms=latency,
                server_version=response.headers.get("server"),
                warnings=warnings,
            ),
            self.spec,
        )

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef | None = None,
        *,
        limit: int = 10_000,
        cursor: str | None = None,
    ) -> ReadResult:
        from service_connectors.flatten import flatten_records

        path = stream.name if stream is not None else str(config.get("path") or "/")
        strategy = str(config.get("pagination") or "none")
        page_size = int(config.get("page_size") or 100)
        names = PageParams.from_config(config)
        collected: list[dict[str, Any]] = []
        warnings: list[str] = []
        truncated = False
        next_params: dict[str, Any] = {**_query_params(config)}
        if strategy in ("page", "offset"):
            next_params.update(
                next_page_request(
                    strategy=strategy,
                    page_index=0,
                    page_size=page_size,
                    payload=None,
                    headers={},
                    cursor_path=None,
                    names=names,
                )
                or {}
            )
        if cursor:
            next_params[names.cursor] = cursor

        with self._client(config) as client:
            url = path
            for page_index in range(MAX_PAGES):
                response = self._get_with_backoff(client, url, next_params)
                payload = response.json()
                records = extract_records(payload, config.get("records_path"))
                collected.extend(records)

                if len(collected) >= limit:
                    collected = collected[:limit]
                    truncated = True
                    break
                if not records:
                    break

                following = next_page_request(
                    strategy=strategy,
                    page_index=page_index + 1,
                    page_size=page_size,
                    payload=payload,
                    headers=dict(response.headers),
                    cursor_path=config.get("cursor_path"),
                    names=names,
                )
                if following is None:
                    break
                if "__url__" in following:
                    url = resolve_next_url(str(config["base_url"]), following.pop("__url__"))
                    # The server built that address; it already carries whatever
                    # filter and page size it wants. Only the credential is
                    # added back, and only when it travels in the query string.
                    #
                    # It is merged into the URL rather than passed alongside it,
                    # because httpx's `params=` *replaces* a URL's query rather
                    # than adding to it -- so an empty dict here threw away the
                    # page marker and asked for page one, forever.
                    url = merge_query(url, _auth_query_params(config))
                    next_params = None
                else:
                    next_params = {**_query_params(config), **following}
            else:
                truncated = True
                warnings.append(
                    f"Stopped after {MAX_PAGES} pages. Narrow the request or raise the row limit."
                )

        frame = (
            pd.DataFrame(flatten_records(collected))
            if config.get("flatten", True)
            else pd.DataFrame(collected)
        )
        return with_tier_note(
            ReadResult(
                dataframe=frame,
                row_count=len(frame),
                truncated=truncated,
                warnings=warnings,
            ),
            self.spec,
        )

    def _get_with_backoff(self, client, url: str, params: dict[str, Any] | None):
        """One request, waiting out a rate limit but nothing else.

        `params` of None means "the URL already says everything" -- an empty
        dict would not: httpx replaces the query with whatever it is given.
        """
        for attempt in range(4):
            response = client.get(url, params=params)
            if response.status_code == 429:
                time.sleep(retry_delay_seconds(dict(response.headers), attempt))
                continue
            if response.status_code >= 400:
                raise ConnectorError(
                    f"The API answered {response.status_code} for {url}.",
                    retryable=response.status_code >= 500,
                )
            return response
        raise ConnectorError("The API kept rate-limiting this request.", retryable=True)


class GraphQlConnector(RestConnector):
    """A GraphQL endpoint, which is one POST rather than many GETs."""

    spec = ConnectorSpec(
        type="graphql",
        label="GraphQL",
        category="api",
        description="Run a GraphQL query and read the result as a table.",
        tier=Tier.CONTAINER,
        verified_by="test_rest_connector.py",
        config_fields=(
            ConfigField("base_url", "Endpoint URL", placeholder="https://api.example.com/graphql"),
            ConfigField("query", "Query", kind="text"),
            ConfigField(
                "records_path",
                "Records path",
                help="Where the list sits under 'data', e.g. 'data.orders.nodes'.",
            ),
            ConfigField(
                "auth_method",
                "Authentication",
                kind="select",
                required=False,
                options=AUTH_METHODS,
                default="bearer",
            ),
            ConfigField("auth_secret", "Token", kind="secret", required=False),
            ConfigField("auth_header_name", "Header name", required=False, default="X-API-Key"),
            ConfigField("auth_query_name", "Query parameter", required=False, default="api_key"),
            ConfigField("auth_username", "Username", required=False),
            ConfigField(
                "flatten", "Flatten nested fields", kind="boolean", required=False, default=True
            ),
        ),
        capabilities=frozenset({"test", "read"}),
    )

    def _post(self, config: dict[str, Any]) -> Any:
        import httpx

        with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.post(
                str(config["base_url"]),
                json={"query": str(config.get("query") or "")},
                headers={**_headers(config), "Content-Type": "application/json"},
            )
        if response.status_code >= 400:
            raise ConnectorError(f"The endpoint answered {response.status_code}.")
        payload = response.json()
        if isinstance(payload, dict) and payload.get("errors"):
            first = payload["errors"][0]
            message = first.get("message") if isinstance(first, dict) else str(first)
            raise ConnectorError(f"GraphQL error: {message}")
        return payload

    def test(self, config: dict[str, Any]) -> TestResult:
        started = time.perf_counter()
        try:
            payload = self._post(config)
            records = extract_records(payload, config.get("records_path"))
        except ConnectorError as exc:
            return TestResult(success=False, message=exc.message)
        except Exception as exc:  # noqa: BLE001
            return TestResult(success=False, message=f"Could not reach the endpoint: {exc}")

        return TestResult(
            success=True,
            message=f"Query ran. {len(records)} record(s) returned.",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef | None = None,
        *,
        limit: int = 10_000,
        cursor: str | None = None,
    ) -> ReadResult:
        from service_connectors.flatten import flatten_records

        payload = self._post(config)
        records = extract_records(payload, config.get("records_path"))
        truncated = len(records) > limit
        records = records[:limit]

        frame = (
            pd.DataFrame(flatten_records(records))
            if config.get("flatten", True)
            else pd.DataFrame(records)
        )
        return ReadResult(dataframe=frame, row_count=len(frame), truncated=truncated)


REST_CONNECTORS = (RestConnector(), GraphQlConnector())
