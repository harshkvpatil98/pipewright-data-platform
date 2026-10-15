"""Enrichment and lookups: bring values from somewhere else onto each row (E1).

A lookup never adds rows: each row takes the first match (by the other
dataset's order) or a default, which is what a spreadsheet's VLOOKUP does
and what a join does not. Reference data the platform cannot ship (IP
ranges, company domains, time zone shapes) is a dataset you provide, and
each tool says what shape it needs; a calendar is generated. Lookups that
call a service outside (geocoding) are in Code & escape hatches, behind the
operator's allowed hosts.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, INT64, STRING

from service_transformations.ir.nodes import Node
from service_transformations.tools import register
from service_transformations.tools.builders import require_column, unique_name
from service_transformations.tools.catalogue.combine import comparable
from service_transformations.tools.local import (
    brought,
    columns_of,
    extension,
    handles,
    other_dataset,
    other_label,
    require_other_columns,
)
from service_transformations.tools.spec import EXAMPLE_DATASET, Example, Param, ParamKind, ToolSpec

CATEGORY = "Enrichment & lookup"
DATASET = Param("right_dataset_id", "Look up in", ParamKind.DATASET)
BRING = Param("bring", "Columns to bring", ParamKind.DATASET_COLUMNS)
DEFAULT = Param("default", "When nothing matches", ParamKind.TEXT, required=False, default="",
                help="Leave empty to leave the brought columns empty; or give a value such as Unknown.")
SUFFIX = Param("suffix", "Ending for a name already taken", ParamKind.TEXT, required=False, default="_right")


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...],
             synonyms: tuple[str, ...] = (), column_scoped: bool = False, reads_dataset: bool = True,
             null_answer: bool = False) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=CATEGORY, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, column_scoped=column_scoped, local_only=True, reads_dataset=reads_dataset,
        row_wise=True, null_answer=null_answer, warns_lost=False,
    ))


def _bring_values(frame: pd.DataFrame, other: pd.DataFrame, rows: list[int | None], bring: list[str],
                  config: dict[str, Any]) -> pd.DataFrame:
    out = frame.reset_index(drop=True).copy()
    suffix = config.get("suffix") or "_right"
    default = config.get("default")
    for name in bring:
        source = other[name].to_numpy(dtype=object)
        values = [source[row] if row is not None else (default if default not in (None, "") else None)
                  for row in rows]
        out[name if name not in frame.columns else f"{name}{suffix}"] = pd.Series(values, dtype=object).infer_objects()
    return out


def _first_rows(keys: pd.DataFrame) -> dict[tuple, int]:
    first: dict[tuple, int] = {}
    for position, key in enumerate(keys.itertuples(index=False, name=None)):
        if any(pd.isna(part) for part in key):
            continue
        first.setdefault(key, position)
    return first


# ------------------------------------------------------------------ lookup


def _lookup_build(node: Node, params: dict[str, Any]) -> Node:
    on = columns_of(node, params["on"], "Match on")
    right_on = list(params["right_on"])
    if len(on) != len(right_on):
        raise BadRequestError("Match on and its columns in the other dataset need the same number of columns.")
    bring = list(params["bring"])
    config = {key: params.get(key) for key in ("right_dataset_id", "right_on", "bring", "default", "suffix")}
    return extension(node, "lookup.from_dataset", {**config, "on": on},
                     brought(node, bring, suffix=params.get("suffix") or "_right"))


@handles("lookup.from_dataset")
def _lookup(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    other = other_dataset(config)
    on, right_on, bring = list(config["on"]), list(config["right_on"]), list(config["bring"])
    require_other_columns(other, [*right_on, *bring], "Look up", config)
    left_keys, right_keys = pd.DataFrame(), pd.DataFrame()
    for index, (a, b) in enumerate(zip(on, right_on)):
        left_keys[f"k{index}"], right_keys[f"k{index}"], _ = comparable(frame[a].reset_index(drop=True),
                                                                        other[b].reset_index(drop=True))
    first = _first_rows(right_keys)
    rows = [None if any(pd.isna(part) for part in key) else first.get(key)
            for key in left_keys.itertuples(index=False, name=None)]
    return _bring_values(frame, other.reset_index(drop=True), rows, bring, config)


_REGIONS = ({"code": "N", "region": "North"}, {"code": "S", "region": "South"}, {"code": "N", "region": "Other"})
_declare("lookup.from_dataset", "Look up values", "Bring columns from the first row of another dataset whose key "
         "columns match this row's, or a default; never more rows than before (a VLOOKUP). Look up a key by a "
         "value just as well: match on any column.", _lookup_build,
         Example(rows=({"area": "N"}, {"area": "W"}, {"area": None}),
                 params={"right_dataset_id": EXAMPLE_DATASET, "on": ["area"], "right_on": ["code"],
                         "bring": ["region"], "default": "Unknown"},
                 column="area", output="region", expect=("North", "Unknown", "Unknown"), other=_REGIONS),
         params=(DATASET, Param("on", "Match on", ParamKind.COLUMNS),
                 Param("right_on", "Their columns", ParamKind.DATASET_COLUMNS), BRING, DEFAULT, SUFFIX),
         synonyms=("lookup", "vlookup", "xlookup", "lookup from dataset", "lookup with default", "reverse lookup",
                   "lookup multiple columns", "map values", "calendar join", "lookup from file", "enrich"))


# --------------------------------------------------------------- hierarchy

_WHAT = ("path", "level", "top", "parent")


def _hierarchy_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    what = params.get("what") or "path"
    into = (params.get("into") or "").strip() or unique_name(node, f"{column}_{what}")
    if into in node.schema():
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    config = {key: params.get(key) for key in ("right_dataset_id", "right_key", "right_parent", "right_name", "what",
                                               "separator")}
    return extension(node, "lookup.hierarchy", {**config, "column": column, "into": into},
                     {**node.schema(), into: INT64 if what == "level" else STRING})


@handles("lookup.hierarchy")
def _hierarchy(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    other = other_dataset(config)
    key, parent = config["right_key"], config["right_parent"]
    name = config.get("right_name") or key
    require_other_columns(other, [key, parent, name], "Hierarchy", config)
    text = lambda v: None if pd.isna(v) else str(v).removesuffix(".0") if isinstance(v, float) else str(v)  # noqa: E731
    parents = {text(k): text(p) for k, p in zip(other[key], other[parent]) if text(k) is not None}
    names = {text(k): n for k, n in zip(other[key], other[name]) if text(k) is not None}
    what = config.get("what") or "path"
    separator = config.get("separator") or " > "
    out = frame.copy()
    answers: list[Any] = []
    for value in frame[config["column"]]:
        node = text(value)
        if node is None or node not in parents:
            answers.append(None)
            continue
        chain, seen = [node], {node}
        while parents.get(chain[-1]) not in (None, "") and parents[chain[-1]] in parents:
            step = parents[chain[-1]]
            if step in seen:
                raise BadRequestError(f"{other_label(config)} has a loop: {step} is its own ancestor.")
            chain.append(step)
            seen.add(step)
        if what == "path":
            answers.append(separator.join(str(names.get(n, n)) for n in reversed(chain)))
        elif what == "level":
            answers.append(len(chain))
        elif what == "top":
            answers.append(names.get(chain[-1], chain[-1]))
        else:
            answers.append(names.get(chain[1], chain[1]) if len(chain) > 1 else None)
    out[config["into"]] = pd.Series(answers, dtype="Int64" if what == "level" else object)
    return out


_TREE = ({"id": 1, "parent": None, "name": "All"}, {"id": 2, "parent": 1, "name": "Food"},
         {"id": 3, "parent": 2, "name": "Fruit"})
_declare("lookup.hierarchy", "Look up in a hierarchy", "From a table of items and their parents (a category tree, "
         "an org chart), give each row its path from the top, its level, its top ancestor or its parent.",
         _hierarchy_build,
         Example(rows=({"category": 3}, {"category": 1}, {"category": 9}),
                 params={"right_dataset_id": EXAMPLE_DATASET, "right_key": "id", "right_parent": "parent",
                         "right_name": "name", "what": "path"},
                 column="category", output="category_path", expect=("All > Food > Fruit", "All", None), other=_TREE),
         params=(DATASET, Param("right_key", "Their item", ParamKind.DATASET_COLUMN),
                 Param("right_parent", "Their item's parent", ParamKind.DATASET_COLUMN),
                 Param("right_name", "Their item's name", ParamKind.DATASET_COLUMN, required=False),
                 Param("what", "Give", ParamKind.SELECT, default="path", options=_WHAT),
                 Param("separator", "Path separator", ParamKind.TEXT, required=False, default=" > "),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("hierarchy lookup", "parent child", "tree path", "ancestors", "org chart", "category path"),
         column_scoped=True)


# ------------------------------------------------------------ date dimension

_PARTS = ("year", "quarter", "month", "month name", "week", "day of week", "day name", "day of year", "is weekend",
          "fiscal year", "fiscal quarter", "is holiday")


def _calendar_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    prefix = params.get("prefix") if params.get("prefix") is not None else f"{column}_"
    wanted = list(params.get("parts") or _PARTS[:-1])
    unknown = [part for part in wanted if part not in _PARTS]
    if unknown:
        raise BadRequestError(f"Not a calendar part: {', '.join(unknown)}. Parts: {', '.join(_PARTS)}.")
    if "is holiday" in wanted and not params.get("country"):
        raise BadRequestError("Say which country's holidays, as a two-letter code such as GB.")
    names = {part: f"{prefix}{part.replace(' ', '_')}" for part in wanted}
    schema = dict(node.schema())
    for part, name in names.items():
        if name in schema:
            raise BadRequestError(f"Column {name!r} already exists; choose another prefix.")
        schema[name] = (BOOLEAN if part.startswith("is ") else STRING if part in ("month name", "day name") else INT64)
    # As pairs, in order: a mapping would be stored with its keys sorted.
    return extension(node, "lookup.date_dimension", {"column": column, "names": [[p, n] for p, n in names.items()],
                                                     "start_month": params.get("start_month"),
                                                     "country": params.get("country"), "region": params.get("region")},
                     schema)


@handles("lookup.date_dimension")
def _calendar(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from service_transformations.ir.expressions import Call, Column, Literal
    from service_transformations.ir.pandas_backend import evaluate

    stamps = pd.to_datetime(frame[config["column"]], errors="coerce", format="mixed")
    start = int(config.get("start_month") or 4)
    out = frame.copy()

    def fiscal(function: str) -> pd.Series:
        # The fiscal year and quarter tools' own rule, so the two cannot disagree.
        working = pd.DataFrame({"__when": stamps})
        return evaluate(Call(function, (Column("__when"), Literal(start, INT64))), working)

    parts = {
        "year": stamps.dt.year, "quarter": stamps.dt.quarter, "month": stamps.dt.month,
        "month name": stamps.dt.month_name(), "week": stamps.dt.isocalendar().week.astype("Int64"),
        "day of week": stamps.dt.dayofweek + 1, "day name": stamps.dt.day_name(),
        "day of year": stamps.dt.dayofyear, "is weekend": stamps.dt.dayofweek >= 5,
        "fiscal year": fiscal("fiscal_year"), "fiscal quarter": fiscal("fiscal_quarter"),
    }
    for part, name in config["names"]:
        if part == "is holiday":
            from service_transformations.tools.catalogue.calendar import _holiday

            values = _holiday(False)(frame[config["column"]], config)
        else:
            values = parts[part]
        series = pd.Series(values, index=frame.index).astype(object)
        series[stamps.isna().to_numpy()] = None
        if part.startswith("is "):
            series = series.astype("boolean")
        elif part not in ("month name", "day name"):
            series = pd.to_numeric(series, errors="coerce").astype("Int64")
        out[name] = series
    return out


_declare("lookup.date_dimension", "Add calendar columns", "Add the year, quarter, month and its name, ISO week, day "
         "of the week and its name, day of the year, weekend, fiscal year and quarter (and, given a country, public "
         "holidays) for a date: a date dimension without a table to join.", _calendar_build,
         Example(rows=({"day": "2026-08-23"},), params={"parts": ["year", "month name", "is weekend"]},
                 column="day", output="day_month_name", expect=("August",)),
         params=(Param("parts", "Columns", ParamKind.LIST, required=False, default=[],
                       help="One per line, from: " + ", ".join(_PARTS) + ". Empty gives all but holidays."),
                 Param("prefix", "Start each new name with", ParamKind.TEXT, required=False),
                 Param("start_month", "Fiscal year starts in month", ParamKind.INTEGER, required=False, default=4,
                       minimum=1, maximum=12),
                 Param("country", "Holidays of country", ParamKind.TEXT, required=False, default=""),
                 Param("region", "Holidays of region", ParamKind.TEXT, required=False, default="")),
         synonyms=("date dimension", "calendar columns", "date parts", "date dimension join", "time dimension"),
         column_scoped=True, reads_dataset=False)


# ----------------------------------------------------------- currency rates


def _rates_build(node: Node, params: dict[str, Any]) -> Node:
    for key in ("column", "currency", "date"):
        require_column(node, params.get(key))
    into = (params.get("into") or "").strip() or unique_name(node, f"{params['column']}_converted")
    if into in node.schema():
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    from shared_python.types import FLOAT64

    config = {key: params.get(key) for key in ("right_dataset_id", "column", "currency", "date", "right_currency",
                                               "right_date", "right_rate", "operation")}
    return extension(node, "lookup.currency_rate", {**config, "into": into}, {**node.schema(), into: FLOAT64})


@handles("lookup.currency_rate")
def _rates(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    other = other_dataset(config)
    require_other_columns(other, [config["right_currency"], config["right_date"], config["right_rate"]],
                          "Convert at historical rates", config)
    left = frame.reset_index(drop=True)
    when, rate_when, _ = comparable(left[config["date"]], other[config["right_date"]])
    probe = pd.DataFrame({"__row": np.arange(len(left)), "__key": when,
                          "__cur": left[config["currency"]].map(lambda v: None if pd.isna(v) else str(v).upper())})
    table = pd.DataFrame({"__key": rate_when, "__rate": pd.to_numeric(other[config["right_rate"]], errors="coerce"),
                          "__cur": other[config["right_currency"]].map(
                              lambda v: None if pd.isna(v) else str(v).upper())})
    probe = probe.dropna(subset=["__key", "__cur"])
    table = table.dropna(subset=["__key", "__cur", "__rate"])
    rates = pd.Series(np.nan, index=range(len(left)))
    if len(probe) and len(table):
        for frame_ in (probe, table):
            if not pd.api.types.is_datetime64_any_dtype(frame_["__key"]):
                frame_["__key"] = frame_["__key"].astype(float)
        matched = pd.merge_asof(probe.sort_values("__key"), table.sort_values("__key"), on="__key", by="__cur",
                                direction="backward")
        rates = matched.set_index("__row")["__rate"].reindex(range(len(left)))
    amounts = pd.to_numeric(left[config["column"]], errors="coerce")
    out = left.copy()
    out[config["into"]] = (amounts / rates if config.get("operation") == "divide" else amounts * rates).to_numpy()
    return out


_RATES = ({"currency": "EUR", "from": "2026-01-01", "rate": 0.85}, {"currency": "EUR", "from": "2026-02-01",
                                                                     "rate": 0.87},
          {"currency": "USD", "from": "2026-01-01", "rate": 0.79})
_declare("lookup.currency_rate", "Convert at historical rates", "Convert an amount using the rate for its currency "
         "that was in force on its date, from a table of rates (currency, from date, rate): each row takes the "
         "latest rate on or before its date.", _rates_build,
         Example(rows=({"amount": 100, "cur": "EUR", "on": "2026-01-15"}, {"amount": 100, "cur": "EUR",
                                                                            "on": "2026-02-02"},
                       {"amount": 10, "cur": "USD", "on": "2025-12-31"}),
                 params={"right_dataset_id": EXAMPLE_DATASET, "currency": "cur", "date": "on",
                         "right_currency": "currency", "right_date": "from", "right_rate": "rate"},
                 column="amount", output="amount_converted", expect=(85.0, 87.0, None), other=_RATES),
         params=(DATASET, Param("currency", "Its currency", ParamKind.COLUMN), Param("date", "Its date", ParamKind.COLUMN),
                 Param("right_currency", "Their currency", ParamKind.DATASET_COLUMN),
                 Param("right_date", "Their rate's start date", ParamKind.DATASET_COLUMN),
                 Param("right_rate", "Their rate", ParamKind.DATASET_COLUMN),
                 Param("operation", "Use the rate to", ParamKind.SELECT, required=False, default="multiply",
                       options=("multiply", "divide")),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("currency rate join", "historical exchange rate", "fx conversion", "convert currency by date"),
         column_scoped=True)


# ------------------------------------------------------------ web domains


def _domain(value: Any) -> str | None:
    text = str(value).strip().lower()
    if "@" in text and "://" not in text:
        text = text.rsplit("@", 1)[1]
    parsed = urlparse(text if "://" in text else f"//{text}")
    host = (parsed.hostname or "").removeprefix("www.")
    return host or None


def _company_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    bring = list(params["bring"])
    config = {key: params.get(key) for key in ("right_dataset_id", "right_on", "bring", "default", "suffix")}
    return extension(node, "lookup.company_from_domain", {**config, "column": column},
                     brought(node, bring, suffix=params.get("suffix") or "_right"))


@handles("lookup.company_from_domain")
def _company(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    other = other_dataset(config).reset_index(drop=True)
    require_other_columns(other, [config["right_on"], *config["bring"]], "Company from a domain", config)
    first: dict[str, int] = {}
    for position, value in enumerate(other[config["right_on"]]):
        domain = None if pd.isna(value) else _domain(value)
        if domain:
            first.setdefault(domain, position)

    def find(value: Any) -> int | None:
        domain = None if pd.isna(value) else _domain(value)
        while domain:
            if domain in first:
                return first[domain]
            # mail.acme.co.uk is acme.co.uk's.
            domain = domain.split(".", 1)[1] if domain.count(".") > 1 else None
        return None

    rows = [find(value) for value in frame[config["column"]]]
    return _bring_values(frame, other, rows, list(config["bring"]), config)


_declare("lookup.company_from_domain", "Company from a web domain", "Bring the company for an email address, a "
         "web address or a domain, from a dataset of domains and companies you provide (subdomains find their "
         "parent: mail.acme.com is acme.com's).", _company_build,
         Example(rows=({"email": "ana@sales.acme.com"}, {"email": "ben@gmail.com"}),
                 params={"right_dataset_id": EXAMPLE_DATASET, "right_on": "domain", "bring": ["company"]},
                 column="email", output="company", expect=("Acme", None),
                 other=({"domain": "https://www.acme.com", "company": "Acme"},)),
         params=(DATASET, Param("right_on", "Their domain", ParamKind.DATASET_COLUMN), BRING, DEFAULT, SUFFIX),
         synonyms=("company from domain", "firmographics", "email to company", "domain lookup"), column_scoped=True)


# ------------------------------------------------------------------- IPs


def _ip_number(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (int, np.integer)) or (isinstance(value, float) and float(value).is_integer()):
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    try:
        return int(ipaddress.ip_address(text))
    except ValueError:
        return None


def _ip_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    bring = list(params["bring"])
    config = {key: params.get(key) for key in ("right_dataset_id", "right_low", "right_high", "bring", "default",
                                               "suffix")}
    return extension(node, "lookup.country_from_ip", {**config, "column": column},
                     brought(node, bring, suffix=params.get("suffix") or "_right"))


@handles("lookup.country_from_ip")
def _ip(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    other = other_dataset(config).reset_index(drop=True)
    low, high = config["right_low"], config["right_high"]
    require_other_columns(other, [low, high, *config["bring"]], "Country from an IP address", config)
    ranges = sorted((_ip_number(a), _ip_number(b), row) for row, (a, b) in enumerate(zip(other[low], other[high]))
                    if _ip_number(a) is not None and _ip_number(b) is not None and _ip_number(a) <= _ip_number(b))
    starts = [start for start, _, _ in ranges]

    def find(value: Any) -> int | None:
        number = _ip_number(value)
        if number is None:
            return None
        import bisect

        index = bisect.bisect_right(starts, number) - 1
        if index >= 0 and ranges[index][1] >= number:
            return ranges[index][2]
        return None

    rows = [find(value) for value in frame[config["column"]]]
    return _bring_values(frame, other, rows, list(config["bring"]), config)


_declare("lookup.country_from_ip", "Country from an IP address", "Bring the country (or any column) for an IPv4 or "
         "IPv6 address from a dataset of address ranges you provide, such as DB-IP's free country file (start, end, "
         "country), whose ranges do not overlap.", _ip_build,
         Example(rows=({"ip": "81.2.69.160"}, {"ip": "8.8.8.8"}, {"ip": "nope"}),
                 params={"right_dataset_id": EXAMPLE_DATASET, "right_low": "start", "right_high": "end",
                         "bring": ["country"]},
                 column="ip", output="country", expect=("GB", "US", None),
                 other=({"start": "81.2.69.0", "end": "81.2.69.255", "country": "GB"},
                        {"start": "8.8.8.0", "end": "8.8.8.255", "country": "US"})),
         params=(DATASET, Param("right_low", "Their range starts at", ParamKind.DATASET_COLUMN),
                 Param("right_high", "Their range ends at", ParamKind.DATASET_COLUMN), BRING, DEFAULT, SUFFIX),
         synonyms=("country from ip", "ip geolocation", "geoip", "ip lookup", "ip to country"), column_scoped=True)
