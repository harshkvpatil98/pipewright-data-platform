"""Code and escape hatches: when no tool does it (E1).

- **SQL**: a SELECT over the working data (``FROM input``), read into the IR by
  the same translator as queries across sources, so it is checked, has
  lineage and pushes down like any step.
- **Python**: code run in the notebook's sandbox on ``data``, giving
  ``result`` (or ``data``) back; turned off, with the reason, where the
  sandbox cannot hold its limits, as notebook cells are.
- **JSON queries** in a small, stated subset of jq; an **inline lookup
  table**; **text templates** (``{name}`` from a column).
- **Calling a web service** for each distinct value, only to hosts the
  operator allows (`ENRICHMENT_ALLOWED_HOSTS`), through the outbound guard,
  bounded and cached in the run. Geocoding goes through a Nominatim-style
  service the operator names (`GEOCODER_URL`). A result from outside is never
  kept and reused, never computed incrementally, and a replay calls again:
  each run says so.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import quote, urlparse

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import FLOAT64, STRING
from shared_python.types.lattice import UNKNOWN

from service_transformations.ir.expressions import Call, Case, Cast, Column, Expr, Literal
from service_transformations.ir.nodes import Node, Project
from service_transformations.tools import register
from service_transformations.tools.builders import require_column, unique_name
from service_transformations.tools.local import column_extension, extension, handles
from service_transformations.tools.spec import Accepts, Example, Param, ParamKind, ToolSpec

CATEGORY = "Code & escape hatches"


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...] = (),
             synonyms: tuple[str, ...] = (), column_scoped: bool = False, local_only: bool = True,
             dynamic_columns: bool = False, null_answer: bool = False, row_wise: bool = False,
             accepts: Accepts = Accepts.ANY, category: str = CATEGORY, needs: str = "") -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=category, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, column_scoped=column_scoped, local_only=local_only, dynamic_columns=dynamic_columns,
        null_answer=null_answer, row_wise=row_wise, warns_lost=False, accepts=accepts, needs=needs,
    ))


# ===================================================================== SQL


class _Input:
    """The SQL step's one table: the data at this step."""

    def __init__(self, node: Node) -> None:
        self.node = node

    def table(self, parts: list[str]):
        from service_transformations.ir.from_sql import Table

        if [part.lower() for part in parts] not in (["input"], ["data"]):
            raise BadRequestError("A SQL step reads the data at this step, called input: SELECT ... FROM input.")
        return Table(label="input", kind="step", origin="step:input", name="__sql_step_input__", schema=None,
                     columns=list(self.node.schema().items()))


def _substitute(tree: Node, name: str, replacement: Node) -> Node:
    from dataclasses import fields, replace

    from service_transformations.ir.nodes import Scan

    if isinstance(tree, Scan) and tree.source == name:
        return replacement
    changes = {}
    for field in fields(tree):
        value = getattr(tree, field.name)
        if isinstance(value, Node):
            changes[field.name] = _substitute(value, name, replacement)
    return replace(tree, **changes) if changes else tree


def _sql_build(node: Node, params: dict[str, Any]) -> Node:
    from service_transformations.ir.from_sql import parse, to_ir

    query = (params.get("sql") or "").strip()
    if not query:
        raise BadRequestError("Write a SELECT over input, such as SELECT region, SUM(amount) AS sales FROM input "
                              "GROUP BY region.")
    tree, _ = to_ir(parse(query), _Input(node))
    return _substitute(tree, "__sql_step_input__", node)


_declare("code.sql", "Transform with SQL", "Write a SELECT over the data at this step, called input: filters, new "
         "columns, groups, joins of input with itself and window functions. It is checked and pushed down like any "
         "step, and its columns are known before it runs.", _sql_build,
         Example(rows=({"region": "n", "amount": 10}, {"region": "s", "amount": 5}, {"region": "n", "amount": 1}),
                 params={"sql": "SELECT region, SUM(amount) AS sales FROM input GROUP BY region ORDER BY region"},
                 column="region", output="sales", expect=(11, 5)),
         params=(Param("sql", "SELECT", ParamKind.TEXT, placeholder="SELECT * FROM input WHERE amount > 0"),),
         synonyms=("sql step", "sql", "query", "select", "custom sql", "write sql"), local_only=False)


# ================================================================== Python

#: Set by the workbench, which owns the sandbox: `(code, frame) -> frame`.
_PYTHON_RUNNER: Callable[[str, pd.DataFrame], pd.DataFrame] | None = None


def register_python_runner(runner: Callable[[str, pd.DataFrame], pd.DataFrame]) -> None:
    """The workbench's sandbox, registered so recipes can use it without importing it."""
    global _PYTHON_RUNNER
    _PYTHON_RUNNER = runner


def _python_build(node: Node, params: dict[str, Any]) -> Node:
    if not (params.get("code") or "").strip():
        raise BadRequestError("Write the Python to run: it gets the rows as data and gives back result (or data).")
    return extension(node, "code.python", {"code": params["code"]}, None)


@handles("code.python")
def _python(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if _PYTHON_RUNNER is None:
        raise BadRequestError("Python steps run in the notebook's sandbox, which this server does not have loaded.")
    return _PYTHON_RUNNER(config["code"], frame)


_declare("code.python", "Transform with Python", "Run Python on the rows, as a pandas DataFrame called data; what "
         "it leaves in result (or data) goes on. It runs in the notebook's sandbox, with its limits on memory, "
         "time, imports and the network, and is turned off where those limits cannot be held.", _python_build,
         Example(rows=({"v": 1}, {"v": 2}), params={"code": "result = data.assign(double=data.v * 2)"}, column="v",
                 note="Adds a column double from v. Runs only where the sandbox is usable."),
         params=(Param("code", "Python", ParamKind.TEXT, placeholder="result = data[data.amount > 0]"),),
         synonyms=("python step", "python", "pandas", "custom code", "script"), dynamic_columns=True,
         needs="the notebook sandbox, which holds its limits on Linux")


# ================================================================ JSON query

_TOKEN = re.compile(r'\s*(\.\[\]|\.\[-?\d+\]|\.\["[^"]*"\]|\.[A-Za-z_][\w-]*|\."[^"]*"|\[\]|\[-?\d+\]|\.|\||'
                    r'length|keys|values|first|last|join\("[^"]*"\)|map\([^)]*\)|tostring)')


def jq(document: Any, program: str) -> list[Any]:
    """A subset of jq: paths, [], |, length, keys, values, first, last, join(s), map(path), tostring."""
    results = [document]
    for stage in [part.strip() for part in _split_pipes(program)]:
        if not stage:
            continue
        results = [value for current in results for value in _stage(current, stage)]
    return results


def _split_pipes(program: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for character in program:
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        if character == "|" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += character
    parts.append(current)
    return parts


def _stage(value: Any, stage: str) -> list[Any]:
    if stage in ("length", "keys", "values", "first", "last", "tostring") or stage.startswith(("join(", "map(")):
        return [_function(value, stage)]
    position, outputs = 0, [value]
    while position < len(stage):
        match = _TOKEN.match(stage, position)
        if not match or not match.group(1):
            raise BadRequestError(f"This JSON query does not understand {stage[position:]!r}. It takes paths such "
                                  "as .customer.id, .items[0], .items[], pipes, and length, keys, first, last, "
                                  "join(\", \"), map(.name).")
        token = match.group(1)
        position = match.end()
        outputs = [result for current in outputs for result in _step(current, token)]
    return outputs


def _step(value: Any, token: str) -> list[Any]:
    if token == ".":
        return [value]
    if token in (".[]", "[]"):
        if isinstance(value, list):
            return list(value)
        if isinstance(value, dict):
            return list(value.values())
        return []
    index = re.fullmatch(r"\.?\[(-?\d+)\]", token)
    if index:
        if not isinstance(value, list):
            return [None]
        number = int(index.group(1))
        return [value[number] if -len(value) <= number < len(value) else None]
    key = token[1:]
    if key.startswith('["') or key.startswith('"'):
        key = key.strip('[]"')
    return [value.get(key) if isinstance(value, dict) else None]


def _function(value: Any, stage: str) -> Any:
    if stage == "length":
        return len(value) if isinstance(value, (list, dict, str)) else None
    if stage == "keys":
        return sorted(value) if isinstance(value, dict) else list(range(len(value))) if isinstance(value, list) else None
    if stage == "values":
        return list(value.values()) if isinstance(value, dict) else value
    if stage in ("first", "last"):
        return (value[0] if stage == "first" else value[-1]) if isinstance(value, list) and value else None
    if stage == "tostring":
        return value if isinstance(value, str) else json.dumps(value)
    if stage.startswith("join("):
        separator = stage[len('join("'):-2]
        return separator.join(str(item) for item in value if item is not None) if isinstance(value, list) else None
    inner = stage[len("map("):-1]
    if not isinstance(value, list):
        return None
    return [found for item in value for found in jq(item, inner)]


def _json_values(series: pd.Series, config: dict[str, Any]) -> list[Any]:
    program = config.get("query") or "."
    jq({}, program)  # refuse a query it does not understand before reading any row
    out: list[Any] = []
    for raw in series:
        if pd.isna(raw):
            out.append(None)
            continue
        try:
            document = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            out.append(None)
            continue
        found = [value for value in jq(document, program) if value is not None]
        if not found:
            out.append(None)
        elif len(found) == 1 and not isinstance(found[0], (dict, list)):
            out.append(found[0])
        else:
            out.append(json.dumps(found[0] if len(found) == 1 else found))
    return out


_declare("code.json_query", "Query JSON (jq)", "Take values out of JSON text with a jq-style query: paths "
         "(.customer.id), positions (.items[0]), every element (.items[]), pipes, and length, keys, values, first, "
         "last, join(\", \"), map(.name) and tostring. Several answers come back as a JSON list.",
         column_extension("code.json_query", UNKNOWN, _json_values, keys=("query",)),
         Example(rows=({"j": '{"items": [{"sku": "a"}, {"sku": "b"}]}'}, {"j": "{}"}),
                 params={"query": ".items | map(.sku) | join(\", \")"}, column="j", output="j",
                 expect=("a, b", None)),
         params=(Param("query", "Query", ParamKind.TEXT, placeholder=".items[] | .sku"),),
         synonyms=("jq", "json query", "json path", "extract json", "jmespath"), column_scoped=True, row_wise=True,
         accepts=Accepts.TEXTUAL)


# ======================================================== lookup and template


def _pairs(lines: list[str]) -> list[tuple[str, str]]:
    pairs = []
    for line in lines:
        if "=" not in line:
            raise BadRequestError(f"Write each pair as value=replacement, not {line!r}.")
        key, _, value = line.partition("=")
        pairs.append((key.strip(), value.strip()))
    return pairs


def _inline_lookup(column: Expr, params: dict[str, Any], node: Node) -> Expr:
    pairs = _pairs(params["table"])
    if not pairs:
        raise BadRequestError("List at least one value=replacement.")
    text = Cast(column, STRING) if node.schema()[params["column"]].kind is not STRING.kind else column
    fallback = params.get("default")
    default: Expr = (Literal(str(fallback), STRING) if fallback not in (None, "") else
                     text if params.get("keep_others", True) else Literal(None, STRING))
    case = Case(tuple((Call("eq", (text, Literal(key, STRING))), Literal(value, STRING)) for key, value in pairs),
                default)
    return Case(((Call("is_null", (column,)), Literal(None, STRING)),), case)


def _lookup_build(node: Node, params: dict[str, Any]) -> Node:
    from service_transformations.tools.builders import project_over

    column = require_column(node, params.get("column"))
    return project_over(node, column, _inline_lookup(Column(column), params, node), into=params.get("into") or None)


_declare("code.lookup_table", "Look up in a small table", "Replace values from a table written here, value="
         "replacement on each line (codes to names), keeping or emptying what is not listed, or writing a "
         "default. Pushes down.", _lookup_build,
         Example(rows=({"c": "GB"}, {"c": "FR"}, {"c": "XX"}), params={"table": ["GB=United Kingdom", "FR=France"],
                                                                      "default": "Other"},
                 column="c", output="c", expect=("United Kingdom", "France", "Other")),
         params=(Param("table", "Table", ParamKind.LIST, placeholder="GB=United Kingdom\nFR=France"),
                 Param("default", "For anything else", ParamKind.TEXT, required=False, default=""),
                 Param("keep_others", "Keep values not listed", ParamKind.BOOLEAN, required=False, default=True)),
         synonyms=("lookup table inline", "map values", "code to name", "translate codes", "mapping table"),
         column_scoped=True, local_only=False)

def _template_parts(text: str) -> list[tuple[str, str]]:
    """("text", ...) and ("column", ...) pieces, read left to right: {{ and }} are braces."""
    parts: list[tuple[str, str]] = []
    literal, position = "", 0
    while position < len(text):
        pair = text[position:position + 2]
        if pair in ("{{", "}}"):
            literal += pair[0]
            position += 2
            continue
        if text[position] == "{":
            close = text.find("}", position)
            if close == -1:
                raise BadRequestError("A { in the template has no }; write {{ for a brace.")
            if literal:
                parts.append(("text", literal))
                literal = ""
            parts.append(("column", text[position + 1:close].strip()))
            position = close + 1
            continue
        if text[position] == "}":
            raise BadRequestError("A } in the template has no {; write }} for a brace.")
        literal += text[position]
        position += 1
    if literal:
        parts.append(("text", literal))
    return parts


def _template_build(node: Node, params: dict[str, Any]) -> Node:
    schema = node.schema()
    into = (params.get("into") or "").strip() or unique_name(node, "text")
    if into in schema:
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    parts: list[Expr] = []
    for kind, value in _template_parts(params.get("template") or ""):
        if kind == "text":
            parts.append(Literal(value, STRING))
            continue
        if value not in schema:
            raise BadRequestError(f"The template names {{{value}}}, which is not a column here. "
                                  f"Columns: {', '.join(schema)}.")
        cell = Column(value) if schema[value].kind is STRING.kind else Cast(Column(value), STRING)
        parts.append(Call("coalesce", (cell, Literal("", STRING))))
    if not parts:
        raise BadRequestError("Write the text, with {column} where a column's value goes.")
    made: Expr = parts[0] if len(parts) == 1 else Call("concat", tuple(parts))
    return Project(node, tuple([(name, Column(name)) for name in schema] + [(into, made)]))


_declare("code.template", "Write text from a template", "Write a new text column from a template with {column} "
         "where each column's value goes (an empty value writes nothing; {{ and }} write braces): an email "
         "greeting, a label, a URL.", _template_build,
         Example(rows=({"first": "Ana", "town": "Leeds"}, {"first": "Ben", "town": None}),
                 params={"template": "Dear {first} of {town}"}, column="first", output="text",
                 expect=("Dear Ana of Leeds", "Dear Ben of ")),
         params=(Param("template", "Template", ParamKind.TEXT, placeholder="Dear {first_name},"),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("template render", "mail merge", "format string", "string template", "build text"),
         local_only=False, null_answer=True)


# ============================================================ outside calls

MAX_DISTINCT = 10_000
TIMEOUT_SECONDS = 10.0
CONCURRENCY = 4


def allowed_hosts() -> set[str]:
    return {host.strip().lower() for host in os.environ.get("ENRICHMENT_ALLOWED_HOSTS", "").split(",") if host.strip()}


def _check_url(url: str) -> str:
    from shared_python.outbound import check_host

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BadRequestError("Give an http or https address.")
    host = parsed.hostname.lower()
    allowed = allowed_hosts()
    if host not in allowed and not any(host.endswith(f".{entry.lstrip('*.')}") for entry in allowed
                                       if entry.startswith("*.")):
        raise BadRequestError(
            f"{host} is not a host this deployment may call. An administrator lists the hosts recipes may call in "
            "ENRICHMENT_ALLOWED_HOSTS." if allowed else
            "This deployment calls no web services from recipes: an administrator turns it on by listing the "
            "allowed hosts in ENRICHMENT_ALLOWED_HOSTS.")
    check_host(host)
    return host


def _secret(name: str | None) -> str | None:
    """A secret the operator set (`ENRICHMENT_SECRETS`, JSON of name to value); never kept in a recipe."""
    if not name:
        return None
    try:
        secrets = json.loads(os.environ.get("ENRICHMENT_SECRETS", "") or "{}")
    except ValueError:
        raise BadRequestError("ENRICHMENT_SECRETS is not valid JSON; an administrator must fix it.") from None
    if name not in secrets:
        raise BadRequestError(f"There is no secret called {name!r} in ENRICHMENT_SECRETS.")
    return str(secrets[name])


class _Pacer:
    """At most one request a second to a host whose terms ask for it (OpenStreetMap's Nominatim)."""

    def __init__(self, spacing: float) -> None:
        self.spacing, self.lock, self.last = spacing, threading.Lock(), 0.0

    def wait(self) -> None:
        if not self.spacing:
            return
        with self.lock:
            delay = self.last + self.spacing - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()


def call_each(values: list[str], request: Callable[[Any, str], Any], *, host: str, spacing: float = 0.0
              ) -> dict[str, Any]:
    """One request per distinct value, a few at once, each retried twice; answers by value."""
    import httpx
    from concurrent.futures import ThreadPoolExecutor

    from shared_python.outbound import httpx_request_guard
    from service_transformations.ir.clock import note_outside_read

    note_outside_read()
    distinct = list(dict.fromkeys(values))
    if len(distinct) > MAX_DISTINCT:
        raise BadRequestError(f"{len(distinct):,} different values would each need a call; a step calls for at most "
                              f"{MAX_DISTINCT:,}. Filter or group first.")
    pacer = _Pacer(spacing)
    answers: dict[str, Any] = {}
    failures: list[str] = []
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True, event_hooks={"request": [httpx_request_guard]},
                      headers={"User-Agent": "Pipewright recipe (https://github.com/harshkvpatil98/pipewright-data-platform)"}
                      ) as client:
        def one(value: str) -> None:
            for attempt in range(3):
                try:
                    pacer.wait()
                    answers[value] = request(client, value)
                    return
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500 and exc.response.status_code != 429:
                        failures.append(f"{value}: {exc.response.status_code}")
                        return
                except httpx.HTTPError as exc:
                    if attempt == 2:
                        failures.append(f"{value}: {type(exc).__name__}")
                        return
                time.sleep(0.2 * (attempt + 1))
            failures.append(f"{value}: no answer after three tries")

        workers = 1 if spacing else CONCURRENCY
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, distinct))
    from service_transformations.ir.pandas_backend import warn

    warn(f"Called {host} for {len(distinct):,} different values; a run or a replay calls it again, and its answers "
         "are never kept from one run to the next." + (f" {len(failures):,} had no answer and are empty "
                                                       f"(first: {failures[0]})." if failures else ""))
    return answers


def _http_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    url = params.get("url") or ""
    if "{value}" not in url and (params.get("method") or "GET") == "GET":
        raise BadRequestError("Put {value} in the address where each row's value goes.")
    if urlparse(url).scheme not in ("http", "https"):
        raise BadRequestError("Give an http or https address.")
    into = (params.get("into") or "").strip() or unique_name(node, f"{column}_answer")
    if into in node.schema():
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    keys = ("url", "method", "body", "pick", "header", "secret")
    return extension(node, "code.http_enrich", {"column": column, "into": into, **{k: params.get(k) for k in keys}},
                     {**node.schema(), into: UNKNOWN})


@handles("code.http_enrich")
def _http(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    host = _check_url(config["url"].replace("{value}", "x"))
    secret = _secret(config.get("secret"))
    header = config.get("header") or "Authorization"
    method = (config.get("method") or "GET").upper()
    pick = config.get("pick") or "."

    def request(client, value: str) -> Any:
        url = config["url"].replace("{value}", quote(value, safe=""))
        headers = {header: secret} if secret else {}
        if method == "POST":
            body = (config.get("body") or '{"value": "{value}"}').replace("{value}", json.dumps(value)[1:-1])
            response = client.post(url, content=body, headers={**headers, "Content-Type": "application/json"})
        else:
            response = client.get(url, headers=headers)
        response.raise_for_status()
        found = [v for v in jq(response.json(), pick) if v is not None]
        if not found:
            return None
        return found[0] if len(found) == 1 and not isinstance(found[0], (dict, list)) else json.dumps(
            found[0] if len(found) == 1 else found)

    values = [str(v) for v in frame[config["column"]].dropna()]
    answers = call_each(values, request, host=host) if values else {}
    out = frame.copy()
    out[config["into"]] = [None if pd.isna(v) else answers.get(str(v)) for v in frame[config["column"]]]
    return out


_declare("code.http_enrich", "Look up each value in a web service", "Call a web service once for each different "
         "value (GET with {value} in the address, or POST a JSON body) and keep part of its JSON answer, picked "
         "with a jq-style query. Only hosts an administrator allows; a secret comes from the server's own settings, "
         "never the recipe. The run says how many calls it made.", _http_build,
         Example(rows=({"sku": "a"},), params={"url": "https://api.example.com/items/{value}", "pick": ".name"},
                 column="sku", note="Each different sku is fetched once and its name kept."),
         params=(Param("url", "Address", ParamKind.TEXT, placeholder="https://api.example.com/items/{value}"),
                 Param("method", "Method", ParamKind.SELECT, required=False, default="GET", options=("GET", "POST")),
                 Param("body", "Body for POST", ParamKind.TEXT, required=False, default="",
                       placeholder='{"id": "{value}"}'),
                 Param("pick", "Keep from the answer", ParamKind.TEXT, required=False, default=".",
                       placeholder=".data.name"),
                 Param("secret", "Secret to send", ParamKind.TEXT, required=False, default="",
                       help="The name of a secret in the server's ENRICHMENT_SECRETS."),
                 Param("header", "Send it in the header", ParamKind.TEXT, required=False, default="Authorization"),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("http enrich", "api lookup", "call api", "web service", "rest lookup", "enrich from api"),
         column_scoped=True, needs="a web service on a host the administrator allows")


# ------------------------------------------------------------------ geocoding


def geocoder() -> tuple[str, str, float]:
    url = os.environ.get("GEOCODER_URL", "").strip().rstrip("/")
    if not url:
        raise BadRequestError("Geocoding needs a Nominatim-style service: an administrator sets GEOCODER_URL (and "
                              "allows its host in ENRICHMENT_ALLOWED_HOSTS).")
    host = _check_url(url)
    # OpenStreetMap's own server asks for one request a second at most.
    spacing = 1.0 if host.endswith("openstreetmap.org") else 0.0
    return url, host, spacing


def _geocode_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    prefix = params.get("prefix") if params.get("prefix") is not None else ""
    lat, lon = f"{prefix}latitude", f"{prefix}longitude"
    for name in (lat, lon):
        if name in node.schema():
            raise BadRequestError(f"Column {name!r} already exists; give a prefix.")
    return extension(node, "geo.geocode", {"column": column, "lat": lat, "lon": lon,
                                           "country": params.get("country")},
                     {**node.schema(), lat: FLOAT64, lon: FLOAT64})


@handles("geo.geocode")
def _geocode(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    url, host, spacing = geocoder()

    def request(client, value: str) -> Any:
        query = {"q": value, "format": "jsonv2", "limit": "1"}
        if config.get("country"):
            query["countrycodes"] = str(config["country"]).lower()
        response = client.get(f"{url}/search", params=query)
        response.raise_for_status()
        found = response.json()
        return (float(found[0]["lat"]), float(found[0]["lon"])) if found else None

    values = [str(v) for v in frame[config["column"]].dropna()]
    answers = call_each(values, request, host=host, spacing=spacing) if values else {}
    out = frame.copy()
    places = [None if pd.isna(v) else answers.get(str(v)) for v in frame[config["column"]]]
    out[config["lat"]] = pd.Series([None if p is None else p[0] for p in places], dtype="float64")
    out[config["lon"]] = pd.Series([None if p is None else p[1] for p in places], dtype="float64")
    return out


def _reverse_build(node: Node, params: dict[str, Any]) -> Node:
    lat, lon = (require_column(node, params.get(key)) for key in ("lat", "lon"))
    into = (params.get("into") or "").strip() or unique_name(node, "address")
    if into in node.schema():
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    return extension(node, "geo.reverse_geocode", {"lat": lat, "lon": lon, "into": into, "part": params.get("part")},
                     {**node.schema(), into: STRING})


@handles("geo.reverse_geocode")
def _reverse(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    url, host, spacing = geocoder()
    part = config.get("part") or "address"
    numbers = frame[[config["lat"], config["lon"]]].apply(pd.to_numeric, errors="coerce")
    keys = [None if pd.isna(a) or pd.isna(b) else f"{a:.6f},{b:.6f}" for a, b in numbers.itertuples(index=False,
                                                                                                    name=None)]

    def request(client, value: str) -> Any:
        lat, lon = value.split(",")
        response = client.get(f"{url}/reverse", params={"lat": lat, "lon": lon, "format": "jsonv2"})
        response.raise_for_status()
        found = response.json()
        if part == "address":
            return found.get("display_name")
        return (found.get("address") or {}).get({"country": "country", "country code": "country_code",
                                                  "postcode": "postcode", "city": "city"}[part])

    answers = call_each([k for k in keys if k], request, host=host, spacing=spacing) if any(keys) else {}
    out = frame.copy()
    out[config["into"]] = [None if key is None else answers.get(key) for key in keys]
    return out


_declare("geo.geocode", "Find places from addresses", "The latitude and longitude of each address, from the "
         "Nominatim-style geocoding service an administrator sets (GEOCODER_URL), one call per different address, "
         "at most one a second to OpenStreetMap's own server as it asks.", _geocode_build,
         Example(rows=({"a": "10 Downing Street, London"},), column="a",
                 note="Latitude and longitude columns, from the configured geocoder."),
         params=(Param("country", "Only in country", ParamKind.TEXT, required=False, default="", placeholder="gb"),
                 Param("prefix", "Start the new names with", ParamKind.TEXT, required=False, default="")),
         synonyms=("geocode", "address to coordinates", "lat long from address", "find location"),
         column_scoped=True, category="Geospatial", accepts=Accepts.TEXTUAL,
         needs="a geocoding service the administrator sets")
_declare("geo.reverse_geocode", "Find addresses from places", "The address (or its city, postcode or country) of "
         "each latitude and longitude, from the configured geocoding service.", _reverse_build,
         Example(rows=({"lat": 51.5034, "lon": -0.1276},), params={"lat": "lat", "lon": "lon"}, column="lat",
                 note="An address column, from the configured geocoder."),
         params=(Param("lat", "Latitude", ParamKind.COLUMN), Param("lon", "Longitude", ParamKind.COLUMN),
                 Param("part", "Give", ParamKind.SELECT, required=False, default="address",
                       options=("address", "city", "postcode", "country", "country code")),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("reverse geocode", "coordinates to address", "address from lat long"), category="Geospatial",
         needs="a geocoding service the administrator sets")

