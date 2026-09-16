"""Every promoted manifest, run against the vendor's documented response.

A catalogue of two hundred connectors is worth less than a catalogue of twenty
unless it can say which of them anybody has ever executed. `Tier.SPEC_ONLY` is
the honest default and most of the catalogue sits there; this file is how a
connector earns its way off it.

**What a contract is.** Each entry below states, independently of the shipped
manifest, what the vendor's API reference documents: where the array of records
sits in the body, how the next page is pointed at, what that pointer is called
in the following request, which fields a record carries, and how the credential
is sent. The harness then does two things with it:

1. **Cross-checks the manifest.** A manifest whose `records_path` disagrees with
   the contract fails here, and that is the point -- both were written from the
   vendor's documentation, so a disagreement means one of them is wrong.
2. **Runs the connector against a server that answers that way.** A loopback
   HTTP server built from the contract serves two pages. The real
   `ManifestConnector`, with nothing changed but the address, has to reach the
   second page and produce the declared columns.

**What that does and does not prove.** It proves the connector executes: the
credential reaches the header the vendor wants, pagination actually advances,
the records are found, renames land, and the declared schema matches what comes
back. It does not prove the vendor's live API matches its own documentation --
nothing short of a credential does, which is what `Tier.LIVE` means and why
these stop at `Tier.CONTAINER`. That distinction is the whole tier system:
"◑ Tested" and "✅ Verified" are different claims and are not run together.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

import service_connectors  # noqa: F401  -- assembles the catalogue
from service_connectors.adapters.manifest_rest import ManifestConnector
from service_connectors.manifest import Manifest, load_all
from service_connectors.protocol import StreamRef, Tier
from service_connectors.registry import get

#: What this file is cited as. A connector promoted above tier 4 names the test
#: that backs the claim, and `test_generators.py` checks the citation resolves.
CITATION = "test_vendor_contracts.py"

PAGE_ROWS = 3
#: The token or marker the second request has to carry. One value across every
#: contract, so a request that reached page two is unmistakable in a failure.
PAGE_TWO = "PAGE-TWO"


# --------------------------------------------------------------- the contract


@dataclass(frozen=True)
class VendorContract:
    """One vendor's documented response envelope, stated independently."""

    key: str
    stream: str

    #: Dotted path to the array of records. None when the body *is* the array.
    records_at: str | None
    #: How the next page is asked for, in the manifest's vocabulary.
    pagination: str
    #: Dotted path to the next-page pointer, for cursor and next_url styles.
    pointer_at: str | None = None
    #: The query parameter the *second* request must carry. Declared here rather
    #: than read from the manifest: this is the half being checked.
    next_param: str | None = None
    #: And the value it must carry, when that is not simply the page token.
    next_value: str | None = None

    #: How the credential travels. ("header", name, value-with-{token}) or
    #: ("query", name, "{token}"). None means this stream needs no credential.
    auth: tuple[str, str, str] | None = None

    #: The field paths one documented record carries.
    fields: tuple[str, ...] = ()
    #: The columns the platform should end up with, after flattening and the
    #: manifest's renames. This is where a rename that never fired shows up.
    columns: tuple[str, ...] = ()

    #: Settings a person would fill in: a subdomain, an account id, a table.
    config: dict[str, str] = field(default_factory=dict)
    #: Headers the vendor requires on every request, e.g. an API version.
    required_headers: dict[str, str] = field(default_factory=dict)

    def record(self, index: int) -> dict[str, Any]:
        """One record, nested the way the vendor returns it."""
        document: dict[str, Any] = {}
        for position, path in enumerate(self.fields):
            _put(document, path, f"{self.key}-{index}-{position}")
        return document

    def page(self, first: bool) -> list[dict[str, Any]]:
        base = 0 if first else PAGE_ROWS
        return [self.record(base + offset) for offset in range(PAGE_ROWS)]


def _put(document: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = document
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _wrap(records: Sequence[dict[str, Any]], records_at: str | None) -> Any:
    if not records_at:
        return list(records)
    body: dict[str, Any] = {}
    _put(body, records_at, list(records))
    return body


# ----------------------------------------------------------------- the server


class _ContractHandler(BaseHTTPRequestHandler):
    """Answers exactly the way the contract under test says the vendor does."""

    contract: VendorContract | None = None
    root: str = ""
    seen: list[dict[str, Any]] = []

    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's naming
        contract = type(self).contract
        assert contract is not None, "no contract is under test"
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        type(self).seen.append(
            {"path": parsed.path, "query": query, "headers": dict(self.headers)}
        )

        page = _page_asked_for(contract, query)
        first = page == 1
        # Beyond page two the fixture is exhausted. An API that answered with
        # page one again would look identical to one with infinite pages, and
        # the connector would collect the same rows until `MAX_PAGES`.
        records = contract.page(first) if page <= 2 else []
        pointer = _pointer(contract, parsed.path) if first else None

        headers: dict[str, str] = {}
        if contract.pagination == "link_header" and pointer:
            headers["Link"] = f'<{pointer}>; rel="next"'

        body: Any
        if contract.pagination in ("cursor", "next_url") and pointer:
            body = _wrap(records, contract.records_at)
            if not isinstance(body, dict):
                # A bare array with a body pointer is a contradiction; every
                # such vendor uses a header instead.
                raise AssertionError(f"{contract.key} cannot carry a body pointer")
            _put(body, contract.pointer_at or "next", pointer)
        else:
            body = _wrap(records, contract.records_at)

        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_POST = do_GET  # noqa: N815 - a POST-read stream reads the same fixture


def _mechanics(contract: VendorContract):
    """The manifest's page size and first page number.

    Read from the manifest rather than declared in the contract: these are this
    platform's choices about how hard to push, not claims about the vendor. What
    the contract does declare -- the *name* of the parameter -- is the half that
    could be wrong, and it is checked.
    """
    for stream in MANIFESTS[contract.key].streams:
        if stream.name == contract.stream:
            return stream.pagination.page_size, stream.pagination.start_page
    raise AssertionError(f"{contract.key} has no stream '{contract.stream}'")


def expected_page_two_value(contract: VendorContract) -> str:
    """What the second request must carry, in this strategy's terms."""
    page_size, start_page = _mechanics(contract)
    if contract.pagination == "page":
        return str(start_page + 1)
    if contract.pagination == "offset":
        return str(page_size)
    return contract.next_value or PAGE_TWO


def _page_asked_for(contract: VendorContract, query: dict[str, list[str]]) -> int:
    """Which page this request is for: 1, 2, or past the end of the fixture."""
    if contract.next_param is None:
        return 1
    sent = query.get(contract.next_param, [])
    page_size, start_page = _mechanics(contract)

    if contract.pagination == "page":
        number = int(sent[0]) if sent else start_page
        return max(1, number - start_page + 1)
    if contract.pagination == "offset":
        offset = int(sent[0]) if sent else 0
        return offset // max(page_size, 1) + 1

    if not sent:
        return 1
    if sent == [contract.next_value or PAGE_TWO]:
        return 2
    # A cursor this fixture never issued: the connector invented one.
    raise AssertionError(
        f"{contract.key} asked for {contract.next_param}={sent}, which was never handed out"
    )


def _pointer(contract: VendorContract, path: str) -> str | None:
    """What the first response hands back so the second request can be made."""
    if contract.next_param is None:
        return None
    if contract.pagination == "cursor":
        return PAGE_TWO
    if contract.pagination in ("next_url", "link_header"):
        return f"{_ContractHandler.root}{path}?{contract.next_param}={PAGE_TWO}"
    return None


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
    httpd = _FastHTTPServer(("127.0.0.1", 0), _ContractHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{httpd.server_port}"
    _ContractHandler.root = root
    try:
        yield root
    finally:
        httpd.shutdown()
        httpd.server_close()


# --------------------------------------------------------------- the contracts
#
# Written from each vendor's published API reference. Where one of these
# disagrees with the shipped manifest, one of the two is wrong and the harness
# says which field.

BEARER = ("header", "Authorization", "Bearer {token}")
BASIC = ("header", "Authorization", "Basic {token}")

CONTRACTS: tuple[VendorContract, ...] = (
    VendorContract(
        key="github", stream="repositories",
        records_at=None, pagination="page", next_param="page",
        auth=BEARER,
        fields=("id", "name", "full_name", "private", "created_at", "updated_at", "pushed_at"),
        columns=("id", "name", "full_name", "private", "created_at", "updated_at", "pushed_at"),
        config={"org": "acme"},
    ),
    VendorContract(
        key="gitlab", stream="projects",
        records_at=None, pagination="page", next_param="page",
        auth=BEARER,
        fields=("id", "name", "path_with_namespace", "created_at", "last_activity_at"),
        columns=("id", "name", "path_with_namespace", "created_at", "last_activity_at"),
    ),
    VendorContract(
        key="bitbucket", stream="repositories",
        records_at="values", pagination="next_url", pointer_at="next",
        next_param="page", auth=BASIC,
        fields=("uuid", "name", "full_name"),
        columns=("uuid", "name", "full_name"),
        config={"workspace": "acme"},
    ),
    VendorContract(
        key="slack", stream="users",
        records_at="members", pagination="cursor",
        pointer_at="response_metadata.next_cursor", next_param="cursor",
        auth=BEARER,
        fields=("id", "name", "real_name", "is_bot", "updated"),
        columns=("id", "name", "real_name", "is_bot", "updated"),
    ),
    VendorContract(
        key="zendesk", stream="tickets",
        records_at="tickets", pagination="next_url", pointer_at="links.next",
        next_param="page[after]", auth=BASIC,
        fields=(
            "id", "subject", "status", "priority", "requester_id", "assignee_id",
            "created_at", "updated_at",
        ),
        columns=(
            "id", "subject", "status", "priority", "requester_id", "assignee_id",
            "created_at", "updated_at",
        ),
        config={"subdomain": "acme"},
    ),
    VendorContract(
        key="jira", stream="issues",
        records_at="issues", pagination="offset", next_param="offset",
        auth=BASIC,
        fields=("id", "key", "fields.summary", "fields.status.name", "fields.created", "fields.updated"),
        columns=("id", "key", "summary", "status", "created_at", "updated_at"),
        config={"subdomain": "acme"},
    ),
    VendorContract(
        key="klaviyo", stream="profiles",
        records_at="data", pagination="next_url", pointer_at="links.next",
        next_param="page[cursor]",
        auth=("header", "Authorization", "Klaviyo-API-Key {token}"),
        fields=("id", "attributes.email", "attributes.created", "attributes.updated"),
        columns=("id", "email", "created_at", "updated_at"),
    ),
    VendorContract(
        key="intercom", stream="contacts",
        records_at="data", pagination="cursor",
        pointer_at="pages.next.starting_after", next_param="starting_after",
        auth=BEARER,
        fields=("id", "email", "name", "role", "created_at", "updated_at"),
        columns=("id", "email", "name", "role", "created_at", "updated_at"),
    ),
    VendorContract(
        key="airtable", stream="records",
        records_at="records", pagination="cursor", pointer_at="offset",
        next_param="offset", auth=BEARER,
        fields=("id", "createdTime"),
        columns=("id", "created_at"),
        config={"base_id": "appXXXX", "table_name": "Contacts"},
    ),
    VendorContract(
        key="notion", stream="users",
        records_at="results", pagination="cursor", pointer_at="next_cursor",
        next_param="start_cursor", auth=BEARER,
        fields=("id", "name", "type"),
        columns=("id", "name", "type"),
    ),
    VendorContract(
        key="pagerduty", stream="incidents",
        records_at="incidents", pagination="offset", next_param="offset",
        auth=("header", "Authorization", "Token token={token}"),
        fields=("id", "incident_number", "title", "status", "urgency", "created_at"),
        columns=("id", "incident_number", "title", "status", "urgency", "created_at"),
    ),
    VendorContract(
        key="mailchimp", stream="lists",
        records_at="lists", pagination="offset", next_param="offset",
        auth=BASIC,
        fields=("id", "name", "date_created", "stats.member_count"),
        columns=("id", "name", "date_created", "member_count"),
        config={"datacenter": "us14"},
    ),
    VendorContract(
        key="asana", stream="tasks",
        records_at="data", pagination="cursor", pointer_at="next_page.offset",
        next_param="offset", auth=BEARER,
        fields=("gid", "name", "completed", "created_at", "modified_at", "due_on"),
        columns=("gid", "name", "completed", "created_at", "modified_at", "due_on"),
    ),
    VendorContract(
        key="front", stream="conversations",
        records_at="_results", pagination="next_url", pointer_at="_pagination.next",
        next_param="page_token", auth=BEARER,
        fields=("id", "subject", "status", "created_at"),
        columns=("id", "subject", "status", "created_at"),
    ),
    VendorContract(
        key="freshdesk", stream="tickets",
        records_at=None, pagination="page", next_param="page",
        auth=BASIC,
        fields=("id", "subject", "status", "priority", "created_at", "updated_at"),
        columns=("id", "subject", "status", "priority", "created_at", "updated_at"),
        config={"subdomain": "acme"},
    ),
    VendorContract(
        key="twilio", stream="messages",
        records_at="messages", pagination="page", next_param="page",
        auth=BASIC,
        fields=("sid", "status", "from", "to", "date_sent"),
        columns=("sid", "status", "from_number", "to_number", "sent_at"),
        config={"account_sid": "ACxxxx"},
    ),
    VendorContract(
        key="typeform", stream="forms",
        records_at="items", pagination="page", next_param="page",
        auth=BEARER,
        fields=("id", "title", "last_updated_at"),
        columns=("id", "title", "last_updated_at"),
        config={"form_id": "abc123"},
    ),
    VendorContract(
        key="calendly", stream="scheduled_events",
        records_at="collection", pagination="cursor",
        pointer_at="pagination.next_page_token", next_param="page_token",
        auth=BEARER,
        fields=("uri", "name", "status", "start_time", "end_time", "created_at"),
        columns=("uri", "name", "status", "start_time", "end_time", "created_at"),
    ),
    VendorContract(
        key="zoom", stream="users",
        records_at="users", pagination="cursor", pointer_at="next_page_token",
        next_param="next_page_token", auth=BEARER,
        fields=("id", "email", "first_name", "last_name", "created_at"),
        columns=("id", "email", "first_name", "last_name", "created_at"),
    ),
    VendorContract(
        key="square", stream="customers",
        records_at="customers", pagination="cursor", pointer_at="cursor",
        next_param="cursor", auth=BEARER,
        fields=("id", "given_name", "family_name", "email_address", "created_at", "updated_at"),
        columns=("id", "given_name", "family_name", "email", "created_at", "updated_at"),
    ),
    VendorContract(
        key="chargebee", stream="customers",
        records_at="list", pagination="cursor", pointer_at="next_offset",
        next_param="offset", auth=BASIC,
        fields=("customer.id", "customer.email", "customer.created_at"),
        columns=("id", "email", "created_at"),
        config={"site": "acme"},
    ),
    VendorContract(
        key="recurly", stream="accounts",
        records_at="data", pagination="next_url", pointer_at="next",
        next_param="cursor", auth=BASIC,
        fields=("id", "code", "email", "created_at", "updated_at"),
        columns=("id", "code", "email", "created_at", "updated_at"),
    ),
    VendorContract(
        key="greenhouse", stream="candidates",
        records_at=None, pagination="page", next_param="page",
        auth=BASIC,
        fields=("id", "first_name", "last_name", "created_at", "updated_at"),
        columns=("id", "first_name", "last_name", "created_at", "updated_at"),
    ),
    VendorContract(
        key="servicenow", stream="incidents",
        records_at="result", pagination="offset", next_param="offset",
        auth=BASIC,
        fields=("sys_id", "number", "short_description", "state", "priority", "sys_created_on"),
        columns=("sys_id", "number", "summary", "state", "priority", "created_at"),
        config={"instance": "dev12345"},
    ),
    VendorContract(
        key="posthog", stream="events",
        records_at="results", pagination="next_url", pointer_at="next",
        next_param="after", auth=BEARER,
        fields=("id", "event", "timestamp", "distinct_id"),
        columns=("id", "event", "timestamp", "distinct_id"),
        config={"host": "eu.posthog.com", "project_id": "1"},
    ),
    VendorContract(
        key="pipedrive", stream="deals",
        records_at="data", pagination="offset", next_param="offset",
        auth=("query", "api_token", "{token}"),
        fields=("id", "title", "value", "currency", "status", "add_time", "update_time"),
        columns=("id", "title", "value", "currency", "status", "add_time", "update_time"),
    ),
    VendorContract(
        key="helpscout", stream="conversations",
        records_at="_embedded.conversations", pagination="page",
        next_param="page", next_value="2", auth=BEARER,
        fields=("id", "subject", "status", "createdAt", "userUpdatedAt"),
        columns=("id", "subject", "status", "created_at", "updated_at"),
    ),
    VendorContract(
        key="sentry", stream="projects",
        records_at=None, pagination="none", auth=BEARER,
        fields=("id", "slug", "name", "platform"),
        columns=("id", "slug", "name", "platform"),
        config={"organization": "acme", "project": "web"},
    ),
    VendorContract(
        key="bamboohr", stream="employees",
        records_at="employees", pagination="none", auth=BASIC,
        fields=("id", "displayName", "workEmail", "jobTitle"),
        columns=("id", "display_name", "work_email", "job_title"),
        config={"subdomain": "acme"},
    ),
    VendorContract(
        key="confluence", stream="pages",
        records_at="results", pagination="next_url", pointer_at="_links.next",
        next_param="cursor", auth=BASIC,
        fields=("id", "title", "status"),
        columns=("id", "title", "status"),
        config={"subdomain": "acme"},
    ),
    VendorContract(
        key="linear", stream="issues",
        records_at="data.issues.nodes", pagination="none",
        auth=("header", "Authorization", "{token}"),
        fields=("id", "title", "state.name", "createdAt", "updatedAt"),
        columns=("id", "title", "state", "created_at", "updated_at"),
    ),
    VendorContract(
        key="clickup", stream="teams",
        records_at="teams", pagination="none",
        auth=("header", "Authorization", "{token}"),
        fields=("id", "name"),
        columns=("id", "name"),
        config={"team_id": "42"},
    ),
    VendorContract(
        key="amplitude", stream="cohorts",
        records_at="cohorts", pagination="none", auth=BASIC,
        fields=("id", "name"),
        columns=("id", "name"),
    ),
    VendorContract(
        key="monday", stream="boards",
        records_at="data.boards", pagination="none",
        auth=("header", "Authorization", "{token}"),
        fields=("id", "name"),
        columns=("id", "name"),
    ),
)

BY_KEY = {contract.key: contract for contract in CONTRACTS}

#: The connectors this file backs. `test_generators.py` reads it to check that
#: every tier-2 manifest is actually covered here rather than merely citing it.
VERIFIED_KEYS = frozenset(BY_KEY)


def _manifests() -> dict[str, Manifest]:
    return {manifest.key: manifest for manifest in load_all()}


MANIFESTS = _manifests()


def _ids(contracts: Sequence[VendorContract]) -> list[str]:
    return [f"{contract.key}.{contract.stream}" for contract in contracts]


# ------------------------------------------- the manifest matches the contract


@pytest.mark.parametrize("contract", CONTRACTS, ids=_ids(CONTRACTS))
class TestTheManifestAgreesWithTheVendor:
    """Both were written from the vendor's reference. A disagreement is a bug."""

    def _stream(self, contract: VendorContract):
        manifest = MANIFESTS[contract.key]
        for stream in manifest.streams:
            if stream.name == contract.stream:
                return stream
        raise AssertionError(
            f"{contract.key} has no stream '{contract.stream}'. "
            f"It has: {', '.join(s.name for s in manifest.streams)}."
        )

    def test_the_records_are_where_the_vendor_puts_them(self, contract: VendorContract) -> None:
        assert self._stream(contract).records_path == contract.records_at

    def test_the_pagination_style_matches(self, contract: VendorContract) -> None:
        assert self._stream(contract).pagination.kind == contract.pagination

    def test_the_next_page_pointer_is_where_the_vendor_puts_it(
        self, contract: VendorContract
    ) -> None:
        assert self._stream(contract).pagination.cursor_path == contract.pointer_at

    def test_the_next_request_uses_the_parameter_the_vendor_names(
        self, contract: VendorContract
    ) -> None:
        pagination = self._stream(contract).pagination
        if contract.pagination == "cursor":
            assert pagination.cursor_param == contract.next_param
        elif contract.pagination == "page":
            assert pagination.page_param == contract.next_param
        elif contract.pagination == "offset":
            assert pagination.offset_param == contract.next_param
        else:
            # next_url and link_header are told where to go; there is no
            # parameter for the manifest to get wrong.
            assert contract.pagination in ("next_url", "link_header", "none")

    def test_the_credential_travels_the_way_the_vendor_wants(
        self, contract: VendorContract
    ) -> None:
        auth = MANIFESTS[contract.key].auth
        if contract.auth is None:
            assert auth.kind == "none"
            return
        placement, name, template = contract.auth
        if placement == "query":
            assert auth.kind == "api_key" and auth.placement == "query"
            assert auth.query_param == name
            return
        assert auth.placement == "header"
        if auth.kind == "basic":
            assert template == "Basic {token}"
            return
        assert auth.header == name
        assert auth.template == template

    def test_every_documented_field_is_declared_or_deliberately_absent(
        self, contract: VendorContract
    ) -> None:
        """A manifest that declares a schema has to declare the whole contract.

        A partial schema is worse than none: `columns()` presents it as the
        endpoint's shape, and a caller building a pipeline on it finds the
        missing column only at run time.
        """
        declared = self._stream(contract).schema_fields
        if not declared:
            pytest.skip("this stream does not declare a schema")
        assert set(declared) == set(contract.fields)


# ------------------------------------------------- the connector actually runs


def _connector(
    contract: VendorContract, root: str, *, only_stream: bool = False
) -> ManifestConnector:
    """The shipped manifest, with nothing changed but the address.

    `model_copy` rather than a fixture manifest: auth, paths, pagination,
    records path, renames and schema all come from the file that ships.
    """
    manifest = MANIFESTS[contract.key]
    update: dict[str, Any] = {"base_url": root}
    if only_stream:
        update["streams"] = tuple(
            stream for stream in manifest.streams if stream.name == contract.stream
        )
    return ManifestConnector(manifest.model_copy(update=update))


def _config(contract: VendorContract) -> dict[str, Any]:
    config: dict[str, Any] = dict(contract.config)
    if contract.auth is not None:
        config["auth_secret"] = "s3cret"
        if MANIFESTS[contract.key].auth.kind == "basic":
            config["auth_username"] = "user@example.com"
    return config


@pytest.mark.parametrize("contract", CONTRACTS, ids=_ids(CONTRACTS))
class TestTheConnectorRunsAgainstThatResponse:
    @pytest.fixture(autouse=True)
    def _arrange(self, contract: VendorContract, server: str):
        _ContractHandler.contract = contract
        _ContractHandler.seen = []
        yield
        _ContractHandler.contract = None

    def test_a_connection_test_succeeds(self, contract: VendorContract, server: str) -> None:
        # `test()` reaches for the manifest's first stream, so the manifest is
        # narrowed to the one under contract rather than the fixture pretending
        # to be two endpoints at once.
        result = _connector(contract, server, only_stream=True).test(_config(contract))
        assert result.success, result.message

    def test_it_reads_the_records_out_of_the_envelope(
        self, contract: VendorContract, server: str
    ) -> None:
        result = _connector(contract, server).read(
            _config(contract), StreamRef(name=contract.stream)
        )
        assert result.row_count >= PAGE_ROWS

    def test_it_produces_the_columns_the_manifest_promises(
        self, contract: VendorContract, server: str
    ) -> None:
        result = _connector(contract, server).read(
            _config(contract), StreamRef(name=contract.stream)
        )
        assert sorted(result.dataframe.columns) == sorted(contract.columns)

    def test_it_reaches_the_second_page(self, contract: VendorContract, server: str) -> None:
        """The failure this catches is silent: page one, reported as everything."""
        if contract.next_param is None:
            pytest.skip("this stream does not paginate")
        result = _connector(contract, server).read(
            _config(contract), StreamRef(name=contract.stream)
        )
        assert result.row_count == PAGE_ROWS * 2, (
            "the connector did not reach page two; requests were "
            f"{[entry['query'] for entry in _ContractHandler.seen]}"
        )

    def test_the_second_request_asks_the_way_the_vendor_documents(
        self, contract: VendorContract, server: str
    ) -> None:
        if contract.next_param is None:
            pytest.skip("this stream does not paginate")
        _connector(contract, server).read(_config(contract), StreamRef(name=contract.stream))
        assert len(_ContractHandler.seen) >= 2
        second = _ContractHandler.seen[1]["query"]
        assert second.get(contract.next_param) == [expected_page_two_value(contract)]

    def test_the_credential_reaches_the_right_place(
        self, contract: VendorContract, server: str
    ) -> None:
        if contract.auth is None:
            pytest.skip("this stream needs no credential")
        _connector(contract, server).read(_config(contract), StreamRef(name=contract.stream))
        first = _ContractHandler.seen[0]
        placement, name, template = contract.auth
        if placement == "query":
            assert first["query"].get(name) == ["s3cret"]
            return
        sent = first["headers"].get(name)
        assert sent is not None, f"no {name} header was sent"
        if template == "Basic {token}":
            import base64

            expected = base64.b64encode(b"user@example.com:s3cret").decode()
            assert sent == f"Basic {expected}"
        else:
            assert sent == template.format(token="s3cret")

    def test_the_declared_schema_describes_what_came_back(
        self, contract: VendorContract, server: str
    ) -> None:
        """`columns()` is what the UI shows before a single row is read."""
        connector = _connector(contract, server)
        stream = StreamRef(name=contract.stream)
        declared = MANIFESTS[contract.key].streams
        if not any(s.name == contract.stream and s.schema_fields for s in declared):
            pytest.skip("this stream does not declare a schema")
        promised = {column.name for column in connector.columns(_config(contract), stream)}
        delivered = set(
            connector.read(_config(contract), stream).dataframe.columns
        )
        assert promised == delivered

    def test_the_read_carries_no_unverified_warning(
        self, contract: VendorContract, server: str
    ) -> None:
        """These connectors are tier 2, so the tier-4 caveat must not appear."""
        spec = get(contract.key).spec
        if spec.tier is Tier.SPEC_ONLY:
            pytest.skip("not yet promoted")
        result = _connector(contract, server).read(
            _config(contract), StreamRef(name=contract.stream)
        )
        assert not any("unverified" in warning.lower() for warning in result.warnings)


# --------------------------------------------------------------- the harness


class TestTheHarnessItself:
    def test_every_contract_names_a_shipped_manifest(self) -> None:
        missing = sorted(key for key in BY_KEY if key not in MANIFESTS)
        assert not missing, f"contracts for connectors that do not exist: {missing}"

    def test_a_next_url_contract_states_where_the_address_is(self) -> None:
        for contract in CONTRACTS:
            if contract.pagination in ("cursor", "next_url"):
                assert contract.pointer_at, f"{contract.key} says nothing about its pointer"

    def test_a_paginating_contract_names_its_parameter(self) -> None:
        for contract in CONTRACTS:
            if contract.pagination in ("page", "offset", "cursor"):
                assert contract.next_param, f"{contract.key} names no next-page parameter"

    def test_the_contracts_are_the_tier_two_manifests(self) -> None:
        """The citation has to mean something in both directions.

        A manifest citing this file with no contract here would be claiming
        verification nothing performs; a contract here for a manifest still at
        tier 4 is verification nobody is being told about.
        """
        citing = {
            key
            for key, manifest in MANIFESTS.items()
            if manifest.verified_by == CITATION
        }
        assert citing == VERIFIED_KEYS
