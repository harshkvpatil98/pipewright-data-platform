"""Dates and times: the rest of the roadmap's calendar tools (E1).

Intervals in any unit, reading and writing time zones, public holidays by
country and region (the `holidays` package, which keeps each country's rules
as published), fiscal periods, a calendar of every date in a range, and rows
for the dates a series skipped. All run here: the database date functions
differ in how they treat a month's end and a clock change.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, DATE, INT64, STRING
from shared_python.types.lattice import timestamp

from service_transformations.ir.nodes import Node
from service_transformations.tools import register
from service_transformations.tools.builders import require_column
from service_transformations.tools.local import column_extension, columns_of, extension, handles
from service_transformations.tools.spec import Accepts, Example, Param, ParamKind, ToolSpec

CATEGORY = "Date & time"
WHEN = Accepts.TEMPORAL


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...] = (),
             synonyms: tuple[str, ...] = (), column_scoped: bool = True, null_answer: bool = False,
             adds_rows: bool = False, row_wise: bool = True, accepts: Accepts = WHEN) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=CATEGORY, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, accepts=accepts, column_scoped=column_scoped, local_only=True, null_answer=null_answer,
        adds_rows=adds_rows, row_wise=row_wise, warns_lost=False,
    ))


def _ex(rows, expect, params=None, column="when", output=None) -> Example:
    return Example(rows=tuple({column: row} for row in rows), expect=tuple(expect), params=params or {},
                   column=column, output=output)


def _times(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, errors="coerce", format="mixed")


_UNITS = ("seconds", "minutes", "hours", "days", "weeks", "months", "quarters", "years")


def _shift(sign: int):
    def values(series: pd.Series, config: dict[str, Any]) -> pd.Series:
        amount = float(config.get("amount") or 0) * sign
        unit = config.get("unit") or "days"
        stamps = _times(series)
        if unit in ("months", "quarters", "years"):
            if not float(amount).is_integer():
                raise BadRequestError(f"Add whole {unit}: a part of a month has no fixed length.")
            months = int(amount) * {"months": 1, "quarters": 3, "years": 12}[unit]
            return stamps.map(lambda v: v + pd.DateOffset(months=months) if not pd.isna(v) else None)
        return stamps + pd.to_timedelta(amount, unit={"seconds": "s", "minutes": "min", "hours": "h", "days": "D",
                                                      "weeks": "W"}[unit])

    return values


_AMOUNT = Param("amount", "How many", ParamKind.NUMBER, default=1)
_UNIT = Param("unit", "Of", ParamKind.SELECT, default="days", options=_UNITS)
_declare("date.add_interval", "Add time", "Add an amount of seconds, minutes, hours, days, weeks, months, "
         "quarters or years (a month added to 31 January is 28 or 29 February).",
         column_extension("date.add_interval", timestamp(), _shift(1), keys=("amount", "unit")),
         _ex(["2026-01-31 10:00", None], ["2026-02-28 10:00:00", None], {"amount": 1, "unit": "months"}),
         params=(_AMOUNT, _UNIT), synonyms=("add interval", "plus hours", "add hours", "date add", "shift time"))
_declare("date.subtract_interval", "Subtract time", "Take away an amount of seconds, minutes, hours, days, weeks, "
         "months, quarters or years.", column_extension("date.subtract_interval", timestamp(), _shift(-1),
                                                         keys=("amount", "unit")),
         _ex(["2026-03-01 00:30"], ["2026-03-01 00:00:00"], {"amount": 30, "unit": "minutes"}),
         params=(_AMOUNT, _UNIT), synonyms=("subtract interval", "minus days", "go back", "date sub", "earlier by"))


def _zone_check(zone: str) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise BadRequestError(f"{zone!r} is not a time zone; write it as Europe/London or America/New_York.") from None
    return zone


def _from_zone(series: pd.Series, config: dict[str, Any]) -> pd.Series:
    zone = _zone_check(config.get("zone") or "UTC")
    stamps = _times(series)
    if getattr(stamps.dt, "tz", None) is not None:
        return stamps
    # A time that never happened (clocks going forward) or happened twice
    # (going back) is empty rather than a guess.
    return stamps.dt.tz_localize(zone, ambiguous="NaT", nonexistent="NaT")


def _to_utc(series: pd.Series, config: dict[str, Any]) -> pd.Series:
    stamps = _times(series)
    if getattr(stamps.dt, "tz", None) is None:
        zone = config.get("zone")
        if not zone:
            return stamps.dt.tz_localize("UTC")
        stamps = stamps.dt.tz_localize(_zone_check(zone), ambiguous="NaT", nonexistent="NaT")
    return stamps.dt.tz_convert("UTC")


_ZONE = Param("zone", "Time zone", ParamKind.TEXT, default="Europe/London", placeholder="Europe/London")
_declare("date.from_timezone", "Read as a time zone", "Say which time zone times without one were written in, so "
         "they become exact moments (a time that the clocks skipped, or passed twice, is empty).",
         column_extension("date.from_timezone", timestamp(tz_aware=True), _from_zone, keys=("zone",)),
         _ex(["2026-07-01 09:00"], ["2026-07-01 09:00:00+01:00"], {"zone": "Europe/London"}),
         params=(_ZONE,), synonyms=("from timezone", "localise", "set time zone", "assume time zone"))
_declare("date.to_utc", "Convert to UTC", "Write moments in UTC. Times without a zone are read in the zone given "
         "(or as UTC already when none is).",
         column_extension("date.to_utc", timestamp(tz_aware=True), _to_utc, keys=("zone",)),
         _ex(["2026-07-01 09:00"], ["2026-07-01 08:00:00+00:00"], {"zone": "Europe/London"}),
         params=(Param("zone", "Times without a zone are in", ParamKind.TEXT, required=False, default=""),),
         synonyms=("to utc", "utc", "gmt", "zulu", "normalise time zone"))


def _calendar(config: dict[str, Any]):
    import holidays

    country = (config.get("country") or "").strip().upper()
    region = (config.get("region") or "").strip().upper() or None
    try:
        holidays.country_holidays(country, subdiv=region, years=2026)
    except NotImplementedError:
        raise BadRequestError(f"{country!r} is not a country the holiday calendar knows; use its two-letter code, "
                              "such as GB, US or DE.") from None
    except Exception as exc:  # noqa: BLE001 - the package says which region codes exist
        raise BadRequestError(f"{region!r} is not a region of {country}: {str(exc).split('.')[0]}.") from None
    return lambda years: holidays.country_holidays(country, subdiv=region, years=years)


def _holiday(names: bool):
    def values(series: pd.Series, config: dict[str, Any]) -> list[Any]:
        stamps = _times(series)
        years = sorted({int(year) for year in stamps.dt.year.dropna().unique()})
        known = _calendar(config)(years) if years else {}
        out: list[Any] = []
        for stamp in stamps:
            if pd.isna(stamp):
                out.append(None)
            elif names:
                out.append(known.get(stamp.date()))
            else:
                out.append(stamp.date() in known)
        return out

    return values


_COUNTRY = Param("country", "Country", ParamKind.TEXT, default="GB", placeholder="GB")
_REGION = Param("region", "Region", ParamKind.TEXT, required=False, default="", placeholder="ENG",
                help="For countries whose holidays differ by region: ENG, SCT, WLS, NIR in GB; a state in US or DE.")
_declare("date.is_holiday", "Is a public holiday", "True on the public holidays of a country (and region), from "
         "each country's published rules.", column_extension("date.is_holiday", BOOLEAN, _holiday(False),
                                                             keys=("country", "region")),
         _ex(["2026-12-25", "2026-12-23"], [True, False], {"country": "GB", "region": "ENG"}),
         params=(_COUNTRY, _REGION), synonyms=("is holiday", "holiday", "bank holiday", "public holiday", "holiday calendar"))
_declare("date.holiday_name", "Name of the public holiday", "The name of the public holiday on that day, or "
         "empty.", column_extension("date.holiday_name", STRING, _holiday(True), keys=("country", "region")),
         _ex(["2026-12-25", "2026-12-23"], ["Christmas Day", None], {"country": "GB", "region": "ENG"}),
         params=(_COUNTRY, _REGION), synonyms=("holiday name", "which holiday"))


def _fiscal_period(series: pd.Series, config: dict[str, Any]) -> list[Any]:
    start = int(config.get("start_month") or 4)
    return [None if pd.isna(v) else (int(v.month) - start) % 12 + 1 for v in _times(series)]


_declare("date.fiscal_period", "Fiscal month", "Which month of the financial year (1 to 12), for a year "
         "starting in the month given.", column_extension("date.fiscal_period", INT64, _fiscal_period,
                                                          keys=("start_month",)),
         _ex(["2026-04-15", "2026-03-31"], [1, 12], {"start_month": 4}),
         params=(Param("start_month", "Fiscal year starts in month", ParamKind.INTEGER, default=4, minimum=1,
                       maximum=12),), synonyms=("fiscal period", "financial month", "fiscal month", "period number"))

_FREQUENCIES = {"day": "D", "week": "W-MON", "month": "MS", "quarter": "QS", "year": "YS"}


def _range(stamps: pd.Series, config: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    start = pd.to_datetime(config.get("start"), errors="coerce") if config.get("start") else stamps.min()
    end = pd.to_datetime(config.get("end"), errors="coerce") if config.get("end") else stamps.max()
    if pd.isna(start) or pd.isna(end):
        return None
    if start > end:
        raise BadRequestError("The calendar's start is after its end.")
    return start, end


def _spine_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    into = (params.get("into") or "").strip() or "date"
    return extension(node, "date.spine", {"column": column, "into": into, "every": params.get("every"),
                                          "start": params.get("start"), "end": params.get("end")}, {into: DATE})


@handles("date.spine")
def _spine(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    stamps = _times(frame[config["column"]]).dt.tz_localize(None) if len(frame) else pd.Series(dtype="datetime64[ns]")
    if getattr(stamps.dt, "tz", None) is not None:
        stamps = stamps.dt.tz_localize(None)
    bounds = _range(stamps.dt.normalize(), config)
    if bounds is None:
        return pd.DataFrame({config["into"]: pd.Series(dtype="object")})
    every = _FREQUENCIES[config.get("every") or "day"]
    start, end = bounds
    if every != "D":
        start = pd.Timestamp(start).to_period({"W-MON": "W-SUN", "MS": "M", "QS": "Q", "YS": "Y"}[every]).start_time
    dates = pd.date_range(start, end, freq=every)
    if len(dates) > 1_000_000:
        raise BadRequestError("That calendar would have more than 1,000,000 rows; choose a longer step or a shorter range.")
    return pd.DataFrame({config["into"]: dates.date})


_EVERY = Param("every", "One row every", ParamKind.SELECT, default="day", options=tuple(_FREQUENCIES))
_declare("date.spine", "Make a calendar of dates", "Replace the rows with one row for every day (or week, month, "
         "quarter, year) from this column's earliest date to its latest, or between dates you give: a calendar to "
         "join other data to, with no day missing.", _spine_build,
         Example(rows=({"when": "2026-01-03"}, {"when": "2026-01-01"}), params={"into": "day"}, column="when",
                 output="day", expect=("2026-01-01", "2026-01-02", "2026-01-03")),
         params=(Param("into", "Column name", ParamKind.TEXT, default="date"), _EVERY,
                 Param("start", "From", ParamKind.TEXT, required=False, default="", placeholder="2026-01-01"),
                 Param("end", "To", ParamKind.TEXT, required=False, default="", placeholder="2026-12-31")),
         synonyms=("date spine", "calendar table", "all dates", "date range", "generate dates", "date dimension"),
         adds_rows=True, row_wise=False)


def _fill_dates_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    within = columns_of(node, params.get("within"), "Within each")
    flag = (params.get("flag") or "").strip() or None
    schema = dict(node.schema())
    if flag:
        if flag in schema:
            raise BadRequestError(f"Column {flag!r} already exists. Choose another name.")
        schema[flag] = BOOLEAN
    return extension(node, "date.fill_missing", {"column": column, "within": within, "every": params.get("every"),
                                                 "flag": flag}, schema)


@handles("date.fill_missing")
def _fill_dates(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    column, within, flag = config["column"], list(config.get("within") or []), config.get("flag")
    every = _FREQUENCIES[config.get("every") or "day"]
    out = frame.copy()
    stamps = _times(frame[column])
    if getattr(stamps.dt, "tz", None) is not None:
        stamps = stamps.dt.tz_localize(None)
    out["__when"] = stamps.dt.normalize() if every == "D" else stamps
    if flag:
        out[flag] = False
    groups = [(None, out)] if not within else list(out.groupby(within, dropna=False, sort=False))
    added: list[pd.DataFrame] = []
    for key, part in groups:
        present = part["__when"].dropna()
        if present.empty:
            continue
        wanted = pd.date_range(present.min(), present.max(), freq=every)
        missing = wanted.difference(pd.DatetimeIndex(present.unique()))
        if len(missing) == 0:
            continue
        rows = pd.DataFrame({column: missing, "__when": missing})
        if within:
            values = key if isinstance(key, tuple) else (key,)
            for name, value in zip(within, values):
                rows[name] = value
        if flag:
            rows[flag] = True
        added.append(rows)
    if added:
        out = pd.concat([out, *added], ignore_index=True)
    order = [*within, "__when"] if within else ["__when"]
    out = out.sort_values(order, kind="stable", na_position="last").drop(columns="__when").reset_index(drop=True)
    return out[[*frame.columns, *([flag] if flag else [])]]


_declare("date.fill_missing", "Add rows for missing dates", "Add a row for each date a series skipped, between its "
         "first and last date (within each group), with the other columns empty; optionally a column saying which "
         "rows were added.", _fill_dates_build,
         Example(rows=({"when": "2026-01-01", "sales": 5}, {"when": "2026-01-03", "sales": 7}),
                 params={"flag": "added"}, column="when", output="added", expect=(False, True, False)),
         params=(_EVERY, Param("within", "Within each", ParamKind.COLUMNS, required=False, default=[]),
                 Param("flag", "Mark added rows in a column", ParamKind.TEXT, required=False, default="")),
         synonyms=("fill missing dates", "complete dates", "gap fill dates", "missing days", "densify"),
         adds_rows=False, row_wise=False, null_answer=True)
