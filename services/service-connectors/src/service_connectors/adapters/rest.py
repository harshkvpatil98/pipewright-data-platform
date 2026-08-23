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
from typing import Any

import pandas as pd

from service_connectors.protocol import (
    ConfigField,
    ConnectorError,
    ConnectorSpec,
    ReadResult,
    StreamRef,
    TestResult,
)

PAGINATION_STRATEGIES = ("none", "page", "offset", "cursor", "link_header")
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

    if method == "bearer" and secret:
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


def _query_params(config: dict[str, Any]) -> dict[str, str]:
    params: dict[str, str] = {}
    if str(config.get("auth_method")) == "api_key_query":
        name = str(config.get("auth_query_name") or "api_key")
        params[name] = str(config.get("auth_secret") or "")
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


def next_page_request(
    *,
    strategy: str,
    page_index: int,
    page_size: int,
    payload: Any,
    headers: dict[str, str],
    cursor_path: str | None,
) -> dict[str, Any] | None:
    """The query parameters for the next page, or None when there is no next page."""
    if strategy == "none":
        return None
    if strategy == "page":
        return {"page": page_index + 1, "per_page": page_size}
    if strategy == "offset":
        return {"offset": page_index * page_size, "limit": page_size}
    if strategy == "cursor":
        token = _walk(payload, cursor_path or "next_cursor")
        return {"cursor": str(token)} if token else None
    if strategy == "link_header":
        link = headers.get("link") or headers.get("Link") or ""
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                return {"__url__": url} if url else None
        return None
    raise ConnectorError(f"Unknown pagination strategy '{strategy}'.")


def _walk(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        part = part.strip()
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
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

        return TestResult(
            success=True,
            message=f"Connected. {len(records)} record(s) in the first response.",
            latency_ms=latency,
            server_version=response.headers.get("server"),
            warnings=warnings,
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
                )
                or {}
            )
        if cursor:
            next_params["cursor"] = cursor

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
                )
                if following is None:
                    break
                if "__url__" in following:
                    url = following.pop("__url__")
                    next_params = _query_params(config)
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
        return ReadResult(
            dataframe=frame,
            row_count=len(frame),
            truncated=truncated,
            warnings=warnings,
        )

    def _get_with_backoff(self, client, url: str, params: dict[str, Any]):
        """One request, waiting out a rate limit but nothing else."""
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
