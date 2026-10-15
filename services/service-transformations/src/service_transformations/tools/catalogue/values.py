"""Text, numbers, conversion, missing data, cleansing and privacy: the rest (E1).

The pushable ones are IR (negate, ratio, unit and currency conversion, custom
bins). The rest run here: each says how it decides (an alphabet table, the
commonest words of a language, a rule for UK and US addresses), and keeps the
library's rule that an empty value in stays empty out.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from typing import Any

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import FLOAT64, JSON as JSON_TYPE, STRING, parse as parse_type

from service_transformations.ir.expressions import Call, Case, Column, Expr, Literal
from service_transformations.ir.nodes import Node
from service_transformations.tools import register
from service_transformations.tools.builders import project_over, require_column, unique_name
from service_transformations.tools.local import column_extension, columns_of, each, extension, handles
from service_transformations.tools.reference import (
    CURRENCIES,
    LANGUAGE_WORDS,
    SCRIPTS,
    STREET_WORDS,
    TEMPERATURES,
    TRANSLITERATION,
    UNIT_WORDS,
    UNITS,
    US_STATES,
    unit_dimension,
    unit_names,
)
from service_transformations.tools.spec import Accepts, Example, Param, ParamKind, ToolSpec


def _declare(name: str, title: str, category: str, summary: str, build, example: Example, *,
             params: tuple[Param, ...] = (), synonyms: tuple[str, ...] = (), accepts: Accepts = Accepts.ANY,
             column_scoped: bool = True, local_only: bool = True, null_answer: bool = False,
             dynamic_columns: bool = False, row_wise: bool = True, warns_lost: bool = True) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=category, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, accepts=accepts, column_scoped=column_scoped, local_only=local_only,
        null_answer=null_answer, dynamic_columns=dynamic_columns, row_wise=row_wise, warns_lost=warns_lost,
    ))


def _ex(rows, expect, params=None, column="value", output=None) -> Example:
    return Example(rows=tuple({column: row} for row in rows), expect=tuple(expect), params=params or {},
                   column=column, output=output)


def _ir(fn):
    """A column tool that is one IR expression over the column."""

    def build(node: Node, params: dict[str, Any]) -> Node:
        column = require_column(node, params.get("column"))
        return project_over(node, column, fn(Column(column), params, node), into=params.get("into") or None)

    return build


# ===================================================================== text

TEXT = "Text"


def _transliterate(value: Any) -> str:
    out = []
    for character in str(value):
        lower = character.lower()
        if lower in TRANSLITERATION:
            mapped = TRANSLITERATION[lower]
            out.append(mapped.capitalize() if character != lower and mapped else mapped)
        else:
            out.append(character)
    decomposed = unicodedata.normalize("NFKD", "".join(out))
    return "".join(character for character in decomposed if not unicodedata.combining(character))


_declare("text.transliterate", "Write in Latin letters", TEXT, "Write Cyrillic and Greek in Latin letters and drop "
         "accents (Москва to Moskva, Αθήνα to Athina, Øresund to Oresund), for matching and for systems that "
         "take plain letters only.", column_extension("text.transliterate", STRING, each(_transliterate)),
         _ex(["Москва", "Αθήνα", "Straße", None], ["Moskva", "Athina", "Strasse", None]),
         synonyms=("transliterate", "romanise", "romanize", "latinise", "to ascii", "cyrillic to latin"),
         accepts=Accepts.TEXTUAL)


def _language(value: Any) -> tuple[str | None, float | None]:
    text = str(value)
    counts: dict[str, int] = {}
    for character in text:
        point = ord(character)
        for name, low, high in SCRIPTS:
            if low <= point <= high:
                counts[name] = counts.get(name, 0) + 1
    letters = sum(1 for character in text if character.isalpha())
    if counts and letters and max(counts.values()) / letters > 0.5:
        script = max(counts, key=lambda name: counts[name])
        if script == "cyrillic":
            lowered = text.lower()
            if any(character in lowered for character in "їєіґ"):
                return "uk", 0.9
            if any(character in lowered for character in "ўђјљњћџ"):
                return ("be" if "ў" in lowered else "sr"), 0.9
            return "ru", 0.7
        return script, 0.95
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 3:
        return None, None
    scores = {code: sum(1 for word in words if word in common) for code, common in LANGUAGE_WORDS.items()}
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best, second = ranked[0], ranked[1]
    if best[1] == 0 or best[1] == second[1]:
        return None, None
    confidence = round(min(1.0, best[1] / len(words) * 2) * (1 - second[1] / best[1]), 3)
    return best[0], confidence


def _detect_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    into = (params.get("into") or "").strip() or unique_name(node, f"{column}_language")
    schema = dict(node.schema())
    if into in schema:
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    schema[into] = STRING
    confidence = f"{into}_confidence" if params.get("confidence") else None
    if confidence:
        schema[confidence] = FLOAT64
    return extension(node, "text.detect_language", {"column": column, "into": into, "confidence": confidence},
                     schema)


@handles("text.detect_language")
def _detect(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    found = [(None, None) if pd.isna(value) else _language(value) for value in frame[config["column"]]]
    out[config["into"]] = [code for code, _ in found]
    if config.get("confidence"):
        out[config["confidence"]] = pd.Series([score for _, score in found], dtype="float64")
    return out


_declare("text.detect_language", "Detect the language", TEXT, "Say which language text is written in, as a "
         "two-letter code: by its alphabet where that settles it, otherwise by which of 17 languages' commonest "
         "words it uses. Texts under three words are not guessed; with confidence on, a second column says how "
         "sure (0 to 1).", _detect_build,
         Example(rows=({"v": "the cat is on the mat"}, {"v": "le chat est sur le tapis"}, {"v": "Привет, мир"},
                       {"v": "ok"}), column="v", output="v_language", expect=("en", "fr", "ru", None)),
         params=(Param("confidence", "Add how sure", ParamKind.BOOLEAN, required=False, default=False),),
         synonyms=("detect language", "language detection", "which language", "identify language"),
         accepts=Accepts.TEXTUAL, warns_lost=False)


# ================================================================= numbers

NUMERIC = "Numeric"
NUM = Accepts.NUMERIC

_declare("numeric.negate", "Flip the sign", NUMERIC, "Turn positive into negative and back (credits into "
         "debits).", _ir(lambda column, params, node: Call("neg", (column,))), _ex([5, -2.5, None], [-5, 2.5, None]),
         synonyms=("negate", "minus", "flip sign", "invert sign", "opposite"), accepts=NUM, local_only=False)
_declare("numeric.ratio", "Divide by another column", NUMERIC, "This column divided by another, row by row "
         "(empty where the other is 0 or empty): a conversion rate, a share, a margin.",
         _ir(lambda column, params, node: Call("div", (column, Column(require_column(node, params.get("other")))))),
         Example(rows=({"a": 6, "b": 3}, {"a": 1, "b": 0}, {"a": 2, "b": None}), params={"other": "b", "into": "r"},
                 column="a", output="r", expect=(2.0, None, None)),
         params=(Param("other", "Divided by", ParamKind.COLUMN),),
         synonyms=("ratio", "divide by column", "per", "rate", "share of"), accepts=NUM, local_only=False,
         warns_lost=False)
_declare("numeric.convert_currency", "Convert at a fixed rate", NUMERIC, "Multiply by an exchange rate you give "
         "(for a rate that changes by day, join to a table of rates with Join to the nearest earlier row).",
         _ir(lambda column, params, node: Call("mul", (column, Literal(float(params["rate"]), FLOAT64)))),
         _ex([100, None], [125.0, None], {"rate": 1.25}),
         params=(Param("rate", "Rate", ParamKind.NUMBER, minimum=0),),
         synonyms=("currency convert", "exchange rate", "fx", "convert money"), accepts=NUM, local_only=False)


def _unit_expression(column: Expr, source: str, target: str) -> Expr:
    if unit_dimension(source) != unit_dimension(target):
        raise BadRequestError(f"{source} is a {unit_dimension(source)} and {target} a {unit_dimension(target)}; "
                              "they do not convert.")
    if source in TEMPERATURES:
        scale_in, offset_in = TEMPERATURES[source]
        scale_out, offset_out = TEMPERATURES[target]
        kelvin = Call("add", (Call("mul", (column, Literal(scale_in, FLOAT64))), Literal(offset_in, FLOAT64)))
        return Call("div", (Call("sub", (kelvin, Literal(offset_out, FLOAT64))), Literal(scale_out, FLOAT64)))
    return Call("mul", (column, Literal(UNITS[source][1] / UNITS[target][1], FLOAT64)))


_UNIT_CHOICES = tuple(unit_names())
_declare("numeric.convert_units", "Convert units", NUMERIC, "Convert between units of length, mass, volume, area, "
         "speed, time, data, energy, pressure and temperature (kilometres to miles, °F to °C, MiB to GB).",
         _ir(lambda column, params, node: _unit_expression(column, params["from_unit"], params["to_unit"])),
         _ex([10, 0, None], [6.213712, 0.0, None], {"from_unit": "km", "to_unit": "mi"}),
         params=(Param("from_unit", "From", ParamKind.SELECT, options=_UNIT_CHOICES),
                 Param("to_unit", "To", ParamKind.SELECT, options=_UNIT_CHOICES)),
         synonyms=("unit convert", "units", "metric to imperial", "celsius", "fahrenheit", "miles", "kilograms"),
         accepts=NUM, local_only=False)


def _custom_bins(column: Expr, params: dict[str, Any], node: Node) -> Expr:
    try:
        edges = sorted(float(edge) for edge in params["edges"])
    except ValueError:
        raise BadRequestError("Edges are numbers.") from None
    if len(edges) < 2:
        raise BadRequestError("Give at least two edges: a bin runs from one edge up to the next.")
    labels = list(params.get("labels") or [])
    if labels and len(labels) != len(edges) - 1:
        raise BadRequestError(f"{len(edges) - 1} bins need {len(edges) - 1} labels, not {len(labels)}.")
    branches = []
    for index, (low, high) in enumerate(zip(edges, edges[1:])):
        label = labels[index] if labels else f"{low:g} to {high:g}"
        last = index == len(edges) - 2
        inside = Call("and", (Call("ge", (column, Literal(low, FLOAT64))),
                              Call("le" if last else "lt", (column, Literal(high, FLOAT64)))))
        branches.append((inside, Literal(label, STRING)))
    return Case(tuple(branches), Literal(None, STRING))


_declare("numeric.bin_custom", "Group into chosen ranges", NUMERIC, "Label each value by the range it falls in, "
         "from edges you choose (0, 18, 65, 120 gives 0 to 18, 18 to 65, 65 to 120), with your own labels if "
         "you like. A value outside every range is empty.", _ir(_custom_bins),
         _ex([5, 30, 70, 200, None], ["child", "adult", "senior", None, None],
             {"edges": ["0", "18", "65", "120"], "labels": ["child", "adult", "senior"]}),
         params=(Param("edges", "Edges", ParamKind.LIST, placeholder="0\n18\n65\n120"),
                 Param("labels", "Labels", ParamKind.LIST, required=False, default=[])),
         synonyms=("custom bins", "bands", "ranges", "age groups", "bucket by edges"), accepts=NUM,
         local_only=False, warns_lost=False)


def _group_values(frame: pd.DataFrame, config: dict[str, Any]):
    within = list(config.get("within") or [])
    values = pd.to_numeric(frame[config["column"]], errors="coerce")
    return values, (values.groupby([frame[name] for name in within], dropna=False) if within else None)


def _robust(frame: pd.DataFrame, config: dict[str, Any]) -> pd.Series:
    values, groups = _group_values(frame, config)

    def scale(part: pd.Series) -> pd.Series:
        if part.notna().sum() == 0:
            return part * np.nan
        spread = part.quantile(0.75) - part.quantile(0.25)
        return (part - part.median()) / spread if spread else part * np.nan

    return groups.transform(scale) if groups is not None else scale(values)


def _equal_frequency(frame: pd.DataFrame, config: dict[str, Any]) -> pd.Series:
    values, groups = _group_values(frame, config)
    buckets = int(config["buckets"])

    def label(part: pd.Series) -> pd.Series:
        present = part.dropna()
        if present.empty:
            return pd.Series([None] * len(part), index=part.index, dtype=object)
        ranked = present.rank(method="first")
        numbers = np.ceil(ranked * buckets / len(present)).astype(int)
        edges = present.groupby(numbers).agg(["min", "max"])
        names = {number: f"{low:g} to {high:g}" for number, (low, high) in edges.iterrows()}
        return numbers.map(names).reindex(part.index)

    return groups.transform(label) if groups is not None else label(values)


_WITHIN = Param("within", "Within each", ParamKind.COLUMNS, required=False, default=[])
_declare("numeric.robust_scale", "Scale by the median and spread", NUMERIC, "Subtract the median and divide by "
         "the spread of the middle half (the interquartile range), so outliers do not stretch the scale.",
         column_extension("numeric.robust_scale", FLOAT64, _robust, keys=("within",), frame_aware=True),
         _ex([1, 2, 3, 4, 100], [-1.0, -0.5, 0.0, 0.5, 48.5]), params=(_WITHIN,),
         synonyms=("robust scale", "robust scaling", "median scale", "iqr scale"), accepts=NUM, row_wise=False,
         warns_lost=False)
_declare("numeric.bin_equal_frequency", "Group into equal-size groups", NUMERIC, "Split the values into this "
         "many groups holding about the same number of rows each, labelled by the range each covers.",
         column_extension("numeric.bin_equal_frequency", STRING, _equal_frequency, keys=("buckets", "within"),
                          frame_aware=True),
         _ex([1, 2, 3, 4, 5, 6], ["1 to 2", "1 to 2", "3 to 4", "3 to 4", "5 to 6", "5 to 6"], {"buckets": 3}),
         params=(Param("buckets", "Groups", ParamKind.INTEGER, default=4, minimum=1, maximum=1000), _WITHIN),
         synonyms=("equal frequency bins", "quantile bins", "quantiles", "equal size buckets"), accepts=NUM,
         row_wise=False, warns_lost=False)

# ============================================================== conversion

TYPES = "Type & conversion"


def _decimals(series: pd.Series, config: dict[str, Any]) -> list[Any]:
    from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

    step = Decimal(1).scaleb(-int(config.get("places") or 0))
    out: list[Any] = []
    for value in series:
        if pd.isna(value):
            out.append(None)
            continue
        try:
            # From the value as written, so 1.005 rounds to 1.01 rather than the
            # 1.00 its nearest float would give.
            out.append(Decimal(str(value).strip().replace(",", "")).quantize(step, rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError):
            out.append(None)
    return out


_declare("type.to_decimal", "Change to an exact decimal", TYPES, "Read as a number with this many decimal "
         "places, kept exact rather than as a float and rounded half up from the value as written (1.005 is "
         "1.01): money, quantities that must add up.",
         column_extension("type.to_decimal", parse_type("decimal(38,2)"), _decimals, keys=("places",)),
         _ex(["1.005", "2", "x", None], ["1.01", "2.00", None, None], {"places": 2}),
         params=(Param("places", "Decimal places", ParamKind.INTEGER, default=2, minimum=0, maximum=18),),
         synonyms=("to decimal", "numeric", "exact number", "money type"))


def _as_json(value: Any) -> str:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        value = value.isoformat()
    if isinstance(value, str):
        try:
            return json.dumps(json.loads(value), ensure_ascii=False)
        except ValueError:
            pass
    return json.dumps(value, ensure_ascii=False, default=str)


_declare("type.to_json", "Write as JSON", TYPES, "Write each value as JSON text: text quoted, numbers as numbers, "
         "JSON already there kept as it is.", column_extension("type.to_json", JSON_TYPE, each(_as_json)),
         _ex(["a", 3, None], ['"a"', "3", None]), synonyms=("to json", "json encode", "serialise", "stringify"))


def _as_list(series: pd.Series, config: dict[str, Any]) -> list[Any]:
    separator = config.get("separator") or ","
    return [None if pd.isna(value) else json.dumps([piece.strip() for piece in str(value).split(separator)
                                                     if piece.strip()], ensure_ascii=False) for value in series]


_declare("type.to_list", "Split into a list", TYPES, "Turn text like \"red, green\" into a JSON list "
         "([\"red\", \"green\"]), to explode or count later.",
         column_extension("type.to_list", JSON_TYPE, _as_list, keys=("separator",)),
         _ex(["red, green", None], ['["red", "green"]', None], {"separator": ","}),
         params=(Param("separator", "Separated by", ParamKind.TEXT, default=","),),
         synonyms=("to array", "to list", "split to array", "make list"), accepts=Accepts.TEXTUAL)


def _strip_thousands(series: pd.Series, config: dict[str, Any]) -> list[Any]:
    separator = config.get("separator") or ","
    decimal = "," if separator == "." else "."
    out: list[Any] = []
    for value in series:
        if pd.isna(value):
            out.append(None)
            continue
        text = str(value).strip().replace(separator, "").replace(" ", "").replace(" ", "")
        text = text.replace(decimal, ".")
        try:
            out.append(float(text))
        except ValueError:
            out.append(None)
    return out


_declare("type.strip_thousands", "Remove thousands separators", TYPES, "Read numbers written with thousands "
         "separators (1,234,567 or 1.234.567,89) as numbers.",
         column_extension("type.strip_thousands", FLOAT64, _strip_thousands, keys=("separator",)),
         _ex(["1,234,567", "12", "n/a", None], [1234567.0, 12.0, None, None], {"separator": ","}),
         params=(Param("separator", "Thousands separator", ParamKind.SELECT, default=",",
                       options=(",", ".", " ", "'")),),
         synonyms=("strip thousands", "remove commas", "thousands separator", "grouping"),
         accepts=Accepts.TEXTUAL)

# ============================================================ missing data

MISSING = "Missing data"


def _interpolate(kind: str):
    def values(frame: pd.DataFrame, config: dict[str, Any]) -> pd.Series:
        order = list(config.get("order_by") or [])
        within = list(config.get("within") or [])
        numbers = pd.to_numeric(frame[config["column"]], errors="coerce")
        work = pd.DataFrame({"v": numbers, "__row": np.arange(len(frame))})
        for name in order:
            work[name] = frame[name].to_numpy()
        for name in within:
            work[f"__g_{name}"] = frame[name].to_numpy()
        work = work.sort_values(order + ["__row"], kind="stable") if order else work
        position = (pd.to_numeric(work[order[0]], errors="coerce") if order and
                    pd.api.types.is_numeric_dtype(work[order[0]]) else pd.Series(np.arange(len(work)),
                                                                                index=work.index, dtype=float))
        if order and pd.api.types.is_datetime64_any_dtype(work[order[0]]):
            position = work[order[0]].astype("int64").astype(float)

        def fill(part: pd.DataFrame) -> pd.Series:
            known = part["v"].notna()
            if known.sum() < (3 if kind == "spline" else 2):
                return part["v"]
            x, y = position.loc[part.index], part["v"]
            inside = (x >= x[known].min()) & (x <= x[known].max())
            result = part["v"].copy()
            gaps = ~known & inside & x.notna()
            if not gaps.any():
                return result
            if kind == "linear":
                result[gaps] = np.interp(x[gaps], x[known], y[known])
            else:
                from scipy.interpolate import CubicSpline

                xs, ys = x[known].to_numpy(), y[known].to_numpy()
                unique, first = np.unique(xs, return_index=True)
                result[gaps] = CubicSpline(unique, ys[first])(x[gaps].to_numpy())
            return result

        if within:
            filled = work.groupby([f"__g_{name}" for name in within], dropna=False, group_keys=False)[["v"]].apply(
                fill)
            filled = filled.iloc[:, 0] if isinstance(filled, pd.DataFrame) else filled
        else:
            filled = fill(work)
        return filled.reindex(work.index).sort_index()

    return values


def _interpolation_tool(kind: str):
    builder = column_extension(f"null.interpolate_{kind}", FLOAT64, _interpolate(kind), keys=("order_by", "within"),
                               frame_aware=True, fills=True)

    def build(node: Node, params: dict[str, Any]) -> Node:
        columns_of(node, params.get("order_by"), "In the order of")
        columns_of(node, params.get("within"), "Within each")
        return builder(node, params)

    return build


_ORDER = Param("order_by", "In the order of", ParamKind.COLUMNS, required=False, default=[],
               help="A date or number to space the points by; leave empty to take the rows as evenly spaced.")
_declare("null.interpolate_linear", "Fill gaps along a straight line", MISSING, "Fill an empty value between two "
         "known ones by drawing a straight line between them, spaced by a date or number column. Gaps before the "
         "first or after the last known value stay empty.", _interpolation_tool("linear"),
         _ex([1, None, 3, None], [1.0, 2.0, 3.0, None]), params=(_ORDER, _WITHIN),
         synonyms=("interpolate", "linear interpolation", "fill gaps", "estimate missing"), accepts=NUM,
         row_wise=False, null_answer=True)
_declare("null.interpolate_spline", "Fill gaps along a smooth curve", MISSING, "Fill an empty value between known "
         "ones with a smooth curve through them (a cubic spline), needing at least three known values.",
         _interpolation_tool("spline"), _ex([1, 4, None, 16], [1.0, 4.0, 9.0, 16.0]), params=(_ORDER, _WITHIN),
         synonyms=("spline", "cubic interpolation", "smooth fill", "curve fill"), accepts=NUM, row_wise=False,
         null_answer=True)


def _mostly_empty_build(node: Node, params: dict[str, Any]) -> Node:
    return extension(node, "null.drop_mostly_empty", {"share": params.get("share")}, None)


@handles("null.drop_mostly_empty")
def _mostly_empty(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    share = float(config.get("share") if config.get("share") is not None else 0.5)
    if frame.empty:
        return frame.copy()
    empty = frame.isna().mean()
    keep = [name for name in frame.columns if empty[name] <= share]
    return frame[keep or list(frame.columns[:1])].copy()


_declare("null.drop_mostly_empty", "Drop mostly empty columns", MISSING, "Drop every column whose share of empty "
         "values is above this (0.5 drops columns more than half empty). The first column stays if every one "
         "would go.", _mostly_empty_build,
         Example(rows=({"a": 1, "b": None}, {"a": 2, "b": None}, {"a": 3, "b": 4}), params={"share": 0.5},
                 column="a", output="__columns__", expect=("a",)),
         params=(Param("share", "Drop when more than this share is empty", ParamKind.NUMBER, default=0.5, minimum=0,
                       maximum=1),),
         synonyms=("drop empty columns", "remove sparse columns", "mostly null", "drop null columns"),
         column_scoped=False, dynamic_columns=True, row_wise=False)

# ============================================================== cleansing

CLEAN = "Cleansing"


def _address(value: Any, style: str) -> str:
    words = re.sub(r"\s+", " ", str(value).replace(" ,", ",")).strip().split(" ")
    abbreviations = {short.lower().rstrip("."): short for short in STREET_WORDS.values()}
    out = []
    for word in words:
        bare, tail = re.match(r"^(.*?)([,.]*)$", word).groups()
        key = bare.lower().rstrip(".")
        if style == "abbreviate" and key in STREET_WORDS:
            out.append(STREET_WORDS[key] + tail.replace(".", ""))
        elif style == "expand" and key in abbreviations:
            long = next(full for full, short in STREET_WORDS.items() if short == abbreviations[key])
            out.append(long.capitalize() + tail.replace(".", ""))
        elif bare.isupper() and len(bare) <= 3 or re.search(r"\d", bare):
            out.append(word.upper() if re.fullmatch(r"[a-z]{1,2}\d.*", bare.lower()) else word)
        else:
            out.append(bare.capitalize() + tail)
    return " ".join(out)


_declare("clean.address", "Standardise an address", CLEAN, "Tidy spacing and capitals and write street words one "
         "way: in full (Street, Road) or abbreviated (St, Rd), as UK and US addresses use them.",
         column_extension("clean.address", STRING, lambda series, config: [
             None if pd.isna(v) else _address(v, config.get("style") or "expand") for v in series], keys=("style",)),
         _ex(["12  high st.", "4 elm AVENUE"], ["12 High Street", "4 Elm Avenue"], {"style": "expand"}),
         params=(Param("style", "Street words", ParamKind.SELECT, required=False, default="expand",
                       options=("expand", "abbreviate")),),
         synonyms=("standardise address", "normalise address", "clean address", "address format"),
         accepts=Accepts.TEXTUAL)

_UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)
_US_ZIP = re.compile(r"\b(\d{5}(?:-\d{4})?)\b")


def _address_part(value: Any, part: str) -> str | None:
    text = re.sub(r"\s+", " ", str(value)).strip()
    pieces = [piece.strip() for piece in text.split(",") if piece.strip()]
    if not pieces:
        return None
    country = None
    if pieces and pieces[-1].lower() in ("uk", "united kingdom", "gb", "england", "scotland", "wales",
                                         "usa", "us", "united states", "united states of america"):
        country = pieces.pop()
    postcode = region = None
    found = _UK_POSTCODE.search(text)
    us = _US_ZIP.search(text)
    if found and not us:
        postcode = found.group(1).upper()
        pieces = [_UK_POSTCODE.sub("", piece).strip() for piece in pieces]
    elif us:
        postcode = us.group(1)
        last = pieces[-1] if pieces else ""
        state = re.search(r"\b([A-Z]{2})\b", last)
        if state and state.group(1) in US_STATES:
            region = state.group(1)
        pieces[-1] = _US_ZIP.sub("", re.sub(r"\b[A-Z]{2}\b", "", last)).strip()
    pieces = [piece for piece in pieces if piece]
    street_line = pieces[0] if pieces else ""
    number = re.match(r"^(\d+[A-Za-z]?)\b\s*(.*)$", street_line)
    unit = re.search(r"\b(?:apt|apartment|flat|unit|suite|ste)\.?\s*([\w-]+)", text, re.I)
    city = pieces[-1] if len(pieces) > 1 else None
    if not region and len(pieces) > 2:
        city, region = pieces[-2], pieces[-1]
    answer = {
        "house number": number.group(1) if number else None,
        "street": (number.group(2) if number else street_line) or None,
        "unit": unit.group(1) if unit else None,
        "city": city,
        "region": region,
        "postcode": postcode,
        "country": country,
    }
    return answer[part]


_declare("clean.address_part", "Take part of an address", CLEAN, "Take the house number, street, unit, city, "
         "region, postcode or country from an address written on one line with commas, by UK and US rules (a UK "
         "postcode, a US state and ZIP code). A part it cannot find is empty; other countries' addresses mostly "
         "give the street and city only.",
         column_extension("clean.address_part", STRING, lambda series, config: [
             None if pd.isna(v) else _address_part(v, config.get("part") or "postcode") for v in series],
             keys=("part",)),
         _ex(["10 Downing Street, London, SW1A 2AA", "350 Fifth Avenue, New York, NY 10118"],
             ["SW1A 2AA", "10118"], {"part": "postcode"}),
         params=(Param("part", "Part", ParamKind.SELECT, default="postcode",
                       options=("house number", "street", "unit", "city", "region", "postcode", "country")),),
         synonyms=("parse address", "address components", "postcode from address", "city from address", "zip code"),
         accepts=Accepts.TEXTUAL, warns_lost=False)


def _currency(value: Any) -> str | None:
    text = str(value).strip().lower()
    if text.upper() in CURRENCIES:
        return text.upper()
    for code, names in CURRENCIES.items():
        if text in names:
            return code
    for code, names in CURRENCIES.items():
        for name in names:
            if len(name) == 1 and not name.isalnum() and name in text:
                return code
    return None


_declare("clean.currency_code", "Standardise a currency", CLEAN, "Write a currency as its ISO 4217 code from a "
         "symbol or a name (£ or pounds to GBP, € to EUR); 33 currencies.",
         column_extension("clean.currency_code", STRING, each(_currency)),
         _ex(["£", "euros", "US Dollars", "Usd", "???"], ["GBP", "EUR", "USD", "USD", None]),
         synonyms=("currency code", "iso 4217", "standardise currency", "currency symbol"), accepts=Accepts.TEXTUAL)

_PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "du", "la", "le", "del", "della", "dos", "das", "bin",
              "ibn", "al", "ter", "ten"}
_HONORIFICS = {"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "dame", "lord", "lady", "rev"}


def _name(value: Any, drop_titles: bool) -> str:
    words = re.sub(r"\s+", " ", str(value)).strip().split(" ")
    if drop_titles:
        words = [word for word in words if word.lower().rstrip(".") not in _HONORIFICS] or words
    out = []
    for position, word in enumerate(words):
        lower = word.lower()
        if position and lower in _PARTICLES:
            out.append(lower)
            continue
        parts = re.split(r"([-'’])", lower)
        fixed = "".join(piece.capitalize() if piece not in "-'’" else piece for piece in parts)
        fixed = re.sub(r"^(Mc)([a-z])", lambda m: m.group(1) + m.group(2).upper(), fixed)
        fixed = re.sub(r"^(Mac)([a-z]{3,})", lambda m: m.group(1) + m.group(2).capitalize(), fixed)
        out.append(fixed)
    return " ".join(out)


_declare("clean.person_name", "Standardise a person's name", CLEAN, "Write a name with the capitals people expect "
         "(McDonald, O'Brien, Smith-Jones, Ludwig van Beethoven), tidy spaces, and optionally drop titles such as "
         "Mr and Dr.", column_extension("clean.person_name", STRING, lambda series, config: [
             None if pd.isna(v) else _name(v, bool(config.get("drop_titles"))) for v in series],
             keys=("drop_titles",)),
         _ex(["JOHN  MCDONALD", "mary o'brien", "Dr. jan van der berg"],
             ["John McDonald", "Mary O'Brien", "Jan van der Berg"], {"drop_titles": True}),
         params=(Param("drop_titles", "Drop titles", ParamKind.BOOLEAN, required=False, default=False),),
         synonyms=("standardise name", "proper case name", "name case", "clean name"), accepts=Accepts.TEXTUAL)

_LOOKS = {
    "a number": lambda v: bool(re.fullmatch(r"\s*[-+]?\d[\d,]*(\.\d+)?\s*", str(v))),
    "a date": lambda v: not pd.isna(pd.to_datetime(str(v), errors="coerce", format="mixed")) and bool(
        re.search(r"\d", str(v))),
    "an email": lambda v: bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(v).strip())),
    "text": lambda v: not re.search(r"\d", str(v)),
}


def _swapped_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    other = require_column(node, params.get("other"))
    if column == other:
        raise BadRequestError("Choose two different columns.")
    return extension(node, "clean.fix_swapped", {"column": column, "other": other, "into": [column, other],
                                                 "should_be": params.get("should_be")}, dict(node.schema()))


@handles("clean.fix_swapped")
def _fix_swapped(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from service_transformations.ir.pandas_backend import warn

    column, other = config["column"], config["other"]
    looks = _LOOKS[config.get("should_be") or "a number"]
    out = frame.copy().astype({column: object, other: object})
    mine = [not pd.isna(v) and looks(v) for v in frame[column]]
    theirs = [not pd.isna(v) and looks(v) for v in frame[other]]
    swap = np.array([(not a) and b and not pd.isna(x) for a, b, x in zip(mine, theirs, frame[column])], dtype=bool)
    if swap.any():
        out.loc[swap, [column, other]] = frame.loc[swap, [other, column]].to_numpy()
        warn(f"Swapped {int(swap.sum()):,} rows whose {column!r} held what {other!r} should.")
    return out.infer_objects()


_declare("clean.fix_swapped", "Fix values in the wrong column", CLEAN, "Swap two columns' values on the rows where "
         "this one does not look like what it should hold and the other does (a phone number typed in the name "
         "box). The run says how many rows it swapped.", _swapped_build,
         Example(rows=({"name": "Ana", "phone": "0123"}, {"name": "0456", "phone": "Ben"}),
                 params={"other": "phone", "should_be": "text"}, column="name", output="name",
                 expect=("Ana", "Ben")),
         params=(Param("other", "The other column", ParamKind.COLUMN),
                 Param("should_be", "This column should hold", ParamKind.SELECT, default="a number",
                       options=tuple(_LOOKS))),
         synonyms=("swapped columns", "wrong column", "fix swapped values", "misplaced values"),
         null_answer=True)


def _measurement(value: Any, target: str) -> float | None:
    match = re.fullmatch(r"\s*([-+]?\d[\d,]*\.?\d*)\s*([^\d\s][^\d]*)?\s*", str(value))
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    written = (match.group(2) or "").strip()
    unit = UNIT_WORDS.get(written.lower(), written)
    if unit not in UNITS and unit not in TEMPERATURES:
        unit = next((name for name in (*UNITS, *TEMPERATURES) if name.lower() == unit.lower()), None)
    if unit is None or unit_dimension(unit) != unit_dimension(target):
        return None
    if unit in TEMPERATURES:
        scale_in, offset_in = TEMPERATURES[unit]
        scale_out, offset_out = TEMPERATURES[target]
        return ((number * scale_in + offset_in) - offset_out) / scale_out
    return number * UNITS[unit][1] / UNITS[target][1]


_declare("clean.units", "Standardise measurements", CLEAN, "Read measurements written with their units (\"5 kg\", "
         "\"5000g\", \"11 lbs\") as numbers in one unit; a value without a unit, or in another kind of unit, is "
         "empty.", column_extension("clean.units", FLOAT64, lambda series, config: [
             None if pd.isna(v) else _measurement(v, config["to_unit"]) for v in series], keys=("to_unit",)),
         _ex(["5 kg", "5000g", "2.2 lbs", "tall"], [5.0, 5.0, 0.997903, None], {"to_unit": "kg"}),
         params=(Param("to_unit", "In", ParamKind.SELECT, options=_UNIT_CHOICES),),
         synonyms=("standardise units", "parse measurements", "units in text", "normalise units"),
         accepts=Accepts.TEXTUAL)

# ================================================================ privacy

PRIVACY = "Encoding & privacy"


def _tokens(series: pd.Series, config: dict[str, Any]) -> list[Any]:
    from shared_python.security.reversible_tokens import tokenise

    name = config.get("key_name") or "default"
    return [None if pd.isna(value) else tokenise(str(value), name) for value in series]


_declare("privacy.tokenise", "Replace with a reversible token", PRIVACY, "Replace each value with a token that "
         "stays the same for the same value (so it still joins and groups) and that only an administrator can "
         "turn back, in Administration, each time recorded in the audit log.",
         column_extension("privacy.tokenise", STRING, _tokens, keys=("key_name",)),
         Example(rows=({"email": "ana@example.com"},), params={"key_name": "customers"}, column="email",
                 note="Each value becomes a token beginning tok_, the same every run under the same key name."),
         params=(Param("key_name", "Key name", ParamKind.TEXT, default="default",
                       help="Values tokenised under one key name reveal only under it."),),
         synonyms=("tokenise", "tokenize", "reversible", "encrypt value", "detokenise"))


def _surrogate_build(node: Node, params: dict[str, Any]) -> Node:
    columns = columns_of(node, params["columns"], "Columns")
    into = (params.get("into") or "").strip() or unique_name(node, "key")
    if into in node.schema():
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    return extension(node, "key.surrogate", {"columns": columns, "into": into}, {**node.schema(), into: STRING})


@handles("key.surrogate")
def _surrogate(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    columns = list(config["columns"])

    def text(value: Any) -> str:
        if pd.isna(value):
            return "\x00"
        if isinstance(value, (float, np.floating)) and float(value).is_integer():
            return str(int(value))
        return str(value)

    out[config["into"]] = [hashlib.sha256("\x1f".join(text(v) for v in row).encode("utf-8")).hexdigest()[:16]
                           for row in frame[columns].itertuples(index=False, name=None)]
    return out


_declare("key.surrogate", "Make a key from columns", PRIVACY, "Make one short key from several columns that is "
         "the same whenever they are (a hash of the values): a key for a table that has none.", _surrogate_build,
         Example(rows=({"a": "x", "b": 1}, {"a": "x", "b": 1}, {"a": "y", "b": 1}), params={"columns": ["a", "b"]},
                 column="a", output="key", expect=("5f4c03d55ba8f40f", "5f4c03d55ba8f40f", "e2247c49f6d590a5")),
         params=(Param("columns", "From columns", ParamKind.COLUMNS),),
         synonyms=("surrogate key", "hash key", "composite key", "row key"), column_scoped=False, null_answer=True)


def _uuid_build(node: Node, params: dict[str, Any]) -> Node:
    into = (params.get("into") or "").strip() or unique_name(node, "id")
    if into in node.schema():
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    columns = columns_of(node, params.get("columns"), "From columns")
    return extension(node, "key.uuid", {"into": into, "columns": columns, "seed": params.get("seed")},
                     {**node.schema(), into: STRING})


@handles("key.uuid")
def _uuids(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    columns = list(config.get("columns") or [])
    if columns:
        namespace = uuid.UUID("6f1c4a5e-8d2b-4c3e-9a7f-0b1d2e3f4a5b")
        out[config["into"]] = [str(uuid.uuid5(namespace, "\x1f".join("" if pd.isna(v) else str(v) for v in row)))
                               for row in frame[columns].itertuples(index=False, name=None)]
    else:
        generator = np.random.default_rng(int(config.get("seed") or 1))
        out[config["into"]] = [str(uuid.UUID(bytes=generator.bytes(16), version=4)) for _ in range(len(frame))]
    return out


_declare("key.uuid", "Make an ID for each row", PRIVACY, "Give each row a UUID: made from columns you choose (the "
         "same values always give the same ID), or random but the same every run for the same seed.",
         _uuid_build,
         Example(rows=({"email": "a@x.com"},), params={"columns": ["email"]}, column="email", output="id",
                 expect=("f0a85006-e7b0-5ef7-82fc-c74a2f8ecb05",)),
         params=(Param("columns", "From columns", ParamKind.COLUMNS, required=False, default=[]),
                 Param("seed", "Seed, when random", ParamKind.INTEGER, required=False, default=1, minimum=0)),
         synonyms=("uuid", "guid", "generate id", "unique id", "row id"), column_scoped=False, null_answer=True)
