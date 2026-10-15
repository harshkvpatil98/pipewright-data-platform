"""Code, escape hatches and the recipe itself (E1, T6).

The SQL step's answers match SQLite's for the same query; JSON queries,
templates and inline lookups do what they say; calling a web service goes
only to allowed hosts, once per value, is never kept, and says so; geocoding
reads a Nominatim-shaped service; the Python step runs in the sandbox where
it holds and is refused with the reason where it does not; a step turned
off passes through everywhere; parameters are written in; a branch merges
back step by step and setting by setting.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from shared_python.errors import BadRequestError

from service_transformations.executor import apply_transformation_steps
from service_transformations.steps.context import StepContext


def run(frame: pd.DataFrame, tool: str, **config):
    return apply_transformation_steps(frame, [{"step_type": "tool", "config": {"tool": tool, **config}}], StepContext())


ORDERS = pd.DataFrame({"id": range(1, 9), "region": list("nnsswwnn"), "amount": [5, 7, 3, 9, 1, 2, 8, 4]})


# ---------------------------------------------------------------------- SQL


@pytest.mark.parametrize("query", [
    "SELECT region, SUM(amount) AS sales, COUNT(*) AS orders FROM input GROUP BY region ORDER BY region",
    "SELECT id, amount * 2 AS double FROM input WHERE amount > 3 ORDER BY id",
    "SELECT id, RANK() OVER (PARTITION BY region ORDER BY amount DESC) AS place FROM input ORDER BY id",
    "SELECT DISTINCT region FROM input ORDER BY region LIMIT 2",
])
def test_the_sql_step_gives_sqlites_answer(query: str) -> None:
    out, _ = run(ORDERS, "code.sql", sql=query)
    with sqlite3.connect(":memory:") as db:
        ORDERS.to_sql("input", db, index=False)
        expected = pd.read_sql_query(query, db)
    pd.testing.assert_frame_equal(out.reset_index(drop=True), expected, check_dtype=False)


def test_the_sql_step_pushes_down_and_has_lineage() -> None:
    from service_lineage.columns import build_pipeline_lineage
    from service_transformations.ir.nodes import Scan
    from service_transformations.ir.sql_backend import to_sql
    from service_transformations.tools import build
    from shared_python.types import INT64, STRING

    node = build(Scan("orders", (("id", INT64), ("region", STRING), ("amount", INT64))),
                 {"tool": "code.sql", "sql": "SELECT region, SUM(amount) AS sales FROM input GROUP BY region"})
    assert "SUM(" in to_sql(node, "postgres")
    lineage = build_pipeline_lineage(base_columns=["id", "region", "amount"], steps=[{"step_type": "tool", "config": {
        "tool": "code.sql", "sql": "SELECT region, SUM(amount) AS sales FROM input GROUP BY region"}}])
    assert lineage.output_columns == ["region", "sales"]
    assert {(e.from_column, e.to_column) for e in lineage.steps[0].edges} >= {("amount", "sales")}


def test_the_sql_step_reads_only_input() -> None:
    with pytest.raises(BadRequestError, match="called input"):
        run(ORDERS, "code.sql", sql="SELECT * FROM orders")


# ------------------------------------------------------- JSON, text, lookups


@pytest.mark.parametrize(("query", "expected"), [
    (".customer.id", "C-1"),
    (".items[0].sku", "a"),
    (".items[-1].qty", 3),
    (".items | length", 2),
    (".items | map(.sku) | join(\", \")", "a, b"),
    (".customer | keys", '["id", "name"]'),
    (".items[] | .sku", '["a", "b"]'),
    (".nothing", None),
])
def test_json_queries(query: str, expected) -> None:
    document = json.dumps({"customer": {"id": "C-1", "name": "Ana"}, "items": [{"sku": "a", "qty": 1},
                                                                                {"sku": "b", "qty": 3}]})
    out, _ = run(pd.DataFrame({"j": [document]}), "code.json_query", column="j", query=query)
    value = out["j"].iloc[0]
    assert (None if pd.isna(value) else value) == expected


def test_a_json_query_it_does_not_understand_is_refused_before_any_row() -> None:
    with pytest.raises(BadRequestError, match="does not understand"):
        run(pd.DataFrame({"j": ["{}"]}), "code.json_query", column="j", query=".a ?? .b")


def test_a_template_and_its_braces() -> None:
    out, _ = run(pd.DataFrame({"name": ["Ana"], "n": [3]}), "code.template", template="{{{name}}} has {n} items")
    assert out["text"].tolist() == ["{Ana} has 3 items"]
    with pytest.raises(BadRequestError, match="not a column here"):
        run(pd.DataFrame({"a": [1]}), "code.template", template="{missing}")


def test_an_inline_lookup_pushes_down_and_keeps_or_empties_the_rest() -> None:
    frame = pd.DataFrame({"c": ["GB", "FR", "XX", None]})
    kept, _ = run(frame, "code.lookup_table", column="c", table=["GB=United Kingdom"])
    emptied, _ = run(frame, "code.lookup_table", column="c", table=["GB=United Kingdom"], keep_others=False)
    assert kept["c"].tolist()[:3] == ["United Kingdom", "FR", "XX"] and pd.isna(kept["c"].iloc[3])
    assert emptied["c"].tolist()[0] == "United Kingdom" and emptied["c"].iloc[1:].isna().all()


# ------------------------------------------------------------ outside calls


class _Service(BaseHTTPRequestHandler):
    calls: list[str] = []

    def log_message(self, *args) -> None:  # noqa: D401 - quiet
        pass

    def _send(self, code: int, body) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        _Service.calls.append(self.path)
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path.startswith("/items/"):
            if self.headers.get("X-Key") != "s3cret":
                return self._send(401, {"error": "who are you"})
            sku = url.path.rsplit("/", 1)[1]
            return self._send(200, {"data": {"name": f"Item {sku}"}}) if sku != "gone" else self._send(404, {})
        if url.path == "/search":
            q = query.get("q", [""])[0]
            places = {"10 Downing Street": [{"lat": "51.5034", "lon": "-0.1276"}]}
            return self._send(200, places.get(q, []))
        if url.path == "/reverse":
            return self._send(200, {"display_name": "10 Downing Street, London",
                                    "address": {"country": "United Kingdom", "postcode": "SW1A 2AA"}})
        return self._send(404, {})


class _FastHTTPServer(HTTPServer):
    """Binds without waiting on `socket.getfqdn()`, which blocks ~35s on macOS."""

    def server_bind(self) -> None:
        import socketserver

        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


@pytest.fixture()
def service(monkeypatch) -> Iterator[str]:
    httpd = _FastHTTPServer(("127.0.0.1", 0), _Service)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    _Service.calls = []
    monkeypatch.setenv("OUTBOUND_ALLOW_LOOPBACK", "true")
    monkeypatch.setenv("ENRICHMENT_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("ENRICHMENT_SECRETS", json.dumps({"items": "s3cret"}))
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()


def test_a_web_service_is_called_once_per_value_with_the_server_s_secret(service) -> None:
    frame = pd.DataFrame({"sku": ["a", "b", "a", None, "gone"]})
    out, warnings = run(frame, "code.http_enrich", column="sku", url=f"{service}/items/{{value}}",
                        pick=".data.name", secret="items", header="X-Key")
    assert out["sku_answer"].tolist()[:3] == ["Item a", "Item b", "Item a"]
    assert pd.isna(out["sku_answer"].iloc[3]) and pd.isna(out["sku_answer"].iloc[4])
    assert sorted(_Service.calls) == ["/items/a", "/items/b", "/items/gone"]
    assert any("Called 127.0.0.1 for 3 different values" in w and "1 had no answer" in w for w in warnings)


def test_a_host_that_is_not_allowed_is_refused(service, monkeypatch) -> None:
    monkeypatch.setenv("ENRICHMENT_ALLOWED_HOSTS", "api.example.com")
    with pytest.raises(BadRequestError, match="127.0.0.1 is not a host this deployment may call"):
        run(pd.DataFrame({"sku": ["a"]}), "code.http_enrich", column="sku", url=f"{service}/items/{{value}}")
    monkeypatch.setenv("ENRICHMENT_ALLOWED_HOSTS", "")
    with pytest.raises(BadRequestError, match="calls no web services from recipes"):
        run(pd.DataFrame({"sku": ["a"]}), "code.http_enrich", column="sku", url=f"{service}/items/{{value}}")


def test_what_a_web_service_gave_is_never_kept(service) -> None:
    from service_transformations.ir.clock import watching_reads

    with watching_reads() as reads:
        run(pd.DataFrame({"sku": ["a"]}), "code.http_enrich", column="sku", url=f"{service}/items/{{value}}",
            pick=".data.name", secret="items", header="X-Key")
    assert reads


def test_geocoding_and_back(service, monkeypatch) -> None:
    monkeypatch.setenv("GEOCODER_URL", service)
    out, _ = run(pd.DataFrame({"a": ["10 Downing Street", "Nowhere"]}), "geo.geocode", column="a")
    assert out["latitude"].tolist()[0] == pytest.approx(51.5034) and pd.isna(out["latitude"].iloc[1])
    back, _ = run(pd.DataFrame({"lat": [51.5034], "lon": [-0.1276]}), "geo.reverse_geocode", lat="lat", lon="lon",
                  part="postcode")
    assert back["address"].tolist() == ["SW1A 2AA"]


def test_geocoding_without_a_service_says_who_sets_one(monkeypatch) -> None:
    monkeypatch.delenv("GEOCODER_URL", raising=False)
    with pytest.raises(BadRequestError, match="an administrator sets GEOCODER_URL"):
        run(pd.DataFrame({"a": ["x"]}), "geo.geocode", column="a")


# ----------------------------------------------------- the recipe as a whole


def test_a_step_turned_off_is_skipped_by_the_engine_lineage_and_kept_results() -> None:
    from service_lineage.columns import build_pipeline_lineage
    from service_transformations.prefix_cache import step_keys
    from service_transformations.schemas import TransformationStep

    off = {"step_type": "drop_columns", "config": {"columns": ["amount"], "_enabled": False, "_note": "later"}}
    on = {"step_type": "drop_columns", "config": {"columns": ["amount"]}}
    out, _ = apply_transformation_steps(ORDERS, [off], StepContext())
    assert "amount" in out.columns
    lineage = build_pipeline_lineage(base_columns=list(ORDERS.columns), steps=[off])
    assert lineage.output_columns == list(ORDERS.columns) and "turned off" in lineage.steps[0].notes[0]
    keys = step_keys("base", [TransformationStep(**off), TransformationStep(**on)], None)
    assert keys[0] == "base"
    noted = step_keys("base", [TransformationStep(step_type="drop_columns",
                                                  config={"columns": ["amount"], "_note": "a note"})], None)
    assert noted == step_keys("base", [TransformationStep(**on)], None)


def test_a_group_changes_nothing_a_step_makes() -> None:
    """Steps in a named group (a macro) run, describe and keep results exactly as they would alone."""
    from service_lineage.columns import build_pipeline_lineage
    from service_transformations.prefix_cache import step_keys
    from service_transformations.schemas import TransformationStep

    grouped = [{"step_type": "drop_columns", "config": {"columns": ["amount"], "_group": "Tidy"}},
               {"step_type": "limit_rows", "config": {"count": 2, "_group": "Tidy"}}]
    plain = [{"step_type": "drop_columns", "config": {"columns": ["amount"]}},
             {"step_type": "limit_rows", "config": {"count": 2}}]
    assert apply_transformation_steps(ORDERS, grouped, StepContext())[0].equals(
        apply_transformation_steps(ORDERS, plain, StepContext())[0])
    assert (build_pipeline_lineage(base_columns=list(ORDERS.columns), steps=grouped).output_columns
            == build_pipeline_lineage(base_columns=list(ORDERS.columns), steps=plain).output_columns)
    assert (step_keys("base", [TransformationStep(**step) for step in grouped], None)
            == step_keys("base", [TransformationStep(**step) for step in plain], None))


def test_parameters_are_written_in_by_kind() -> None:
    from service_transformations.parameters import resolve

    steps = [{"step_type": "limit_rows", "config": {"count": "{{n}}"}},
             {"step_type": "derive_column", "config": {"target_column": "t", "formula": '"{{label}}"'}}]
    declared = [{"name": "n", "kind": "whole number", "default": 3}, {"name": "label", "kind": "text",
                                                                       "default": "x"}]
    resolved = resolve(steps, declared, {"label": "north"})
    assert resolved[0]["config"]["count"] == 3 and resolved[1]["config"]["formula"] == '"north"'
    with pytest.raises(BadRequestError, match="is a whole number"):
        resolve(steps, declared, {"n": 2.5})
    with pytest.raises(BadRequestError, match="Give a value for n"):
        resolve(steps, [{"name": "n", "kind": "number"}, {"name": "label"}], {"label": "y"})


class TestMerge:
    BASE = [("a", {"step_type": "limit_rows", "config": {"count": 10}}),
            ("b", {"step_type": "sort_rows", "config": {"columns": ["x"], "ascending": True}})]

    def merge(self, ours, theirs, prefer=None):
        from service_transformations.recipe_management import three_way

        return three_way(self.BASE, ours, theirs, prefer)

    def test_each_side_s_change_is_kept(self) -> None:
        ours = [self.BASE[0], ("b", {"step_type": "sort_rows", "config": {"columns": ["x"], "ascending": False}})]
        theirs = [("a", {"step_type": "limit_rows", "config": {"count": 5}}), self.BASE[1]]
        merged, conflicts, counts = self.merge(ours, theirs)
        assert not conflicts and dict(merged)["a"]["config"]["count"] == 5
        assert dict(merged)["b"]["config"]["ascending"] is False

    def test_different_settings_of_one_step_merge(self) -> None:
        ours = [self.BASE[0], ("b", {"step_type": "sort_rows", "config": {"columns": ["y"], "ascending": True}})]
        theirs = [self.BASE[0], ("b", {"step_type": "sort_rows", "config": {"columns": ["x"], "ascending": False}})]
        merged, conflicts, _ = self.merge(ours, theirs)
        assert not conflicts and dict(merged)["b"]["config"] == {"columns": ["y"], "ascending": False}

    def test_a_removed_and_changed_step_is_a_conflict(self) -> None:
        ours = [self.BASE[1]]
        theirs = [("a", {"step_type": "limit_rows", "config": {"count": 1}}), self.BASE[1]]
        _, conflicts, _ = self.merge(ours, theirs)
        assert conflicts[0].what == "removed from the recipe but changed on the branch"
        merged, _, _ = self.merge(ours, theirs, prefer="branch")
        assert [i for i, _ in merged] == ["a", "b"]

    def test_a_step_added_on_the_branch_goes_after_the_step_it_followed(self) -> None:
        ours = [self.BASE[1], self.BASE[0]]  # the recipe reordered
        theirs = [self.BASE[0], ("new", {"step_type": "drop_null_rows", "config": {}}), self.BASE[1]]
        merged, conflicts, counts = self.merge(ours, theirs)
        assert not conflicts and [i for i, _ in merged] == ["b", "a", "new"] and counts["added"] == 1

    def test_the_branch_s_order_when_the_recipe_kept_its_own(self) -> None:
        theirs = [self.BASE[1], self.BASE[0]]
        merged, _, _ = self.merge(list(self.BASE), theirs)
        assert [i for i, _ in merged] == ["b", "a"]


def test_a_step_that_asks_a_web_service_is_never_run_incrementally() -> None:
    """Its answers can change between runs, so rows made last time cannot stand for this run's."""
    from shared_python.types import STRING

    from service_transformations.incremental import why_not
    from service_transformations.tools import TOOLS
    from service_transformations.ir.nodes import Scan

    scan = Scan("orders", (("sku", STRING), ("city", STRING)))
    for tool in ({"tool": "code.http_enrich", "column": "sku", "url": "https://api.example.com/{value}"},
                 {"tool": "geo.geocode", "column": "city"}):
        reason = why_not([{"step_type": "tool", "config": tool}], scan, "append", None, set())
        assert reason and "asks a web service" in reason, (tool, reason)
    assert all(TOOLS[name].calls_out for name in ("code.http_enrich", "geo.geocode", "geo.reverse_geocode"))
    assert not any(spec.calls_out for name, spec in TOOLS.items()
                   if name not in ("code.http_enrich", "geo.geocode", "geo.reverse_geocode"))
