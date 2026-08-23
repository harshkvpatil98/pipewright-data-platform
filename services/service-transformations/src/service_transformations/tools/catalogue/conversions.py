"""Type and conversion tools."""

from __future__ import annotations

from shared_python.types import parse as parse_type

from service_transformations.ir.expressions import Cast
from service_transformations.tools.builders import call, null_safe, text as lit
from service_transformations.tools.declare import Accepts, Example, Param, ParamKind, custom, simple

CATEGORY = "Type & conversion"

CAST_TARGETS = (
    "text", "int32", "int64", "float64", "decimal(18,2)", "boolean",
    "date", "timestamp", "uuid", "json",
)


def _ex(rows, expect, params=None):
    return Example(
        rows=tuple({"value": row} for row in rows),
        expect=tuple(expect),
        params=params or {},
        column="value",
    )


simple("type.to_text", "To text", CATEGORY,
       "Render as text without inventing decimals.", "to_text",
       accepts=Accepts.ANY, synonyms=("to string", "stringify", "as text"),
       example=_ex([10, None], ["10", None]))

simple("type.to_number", "To number", CATEGORY,
       "Read as a number. Values that will not parse become null.", "to_number",
       accepts=Accepts.ANY, synonyms=("to float", "parse number", "numeric"),
       example=_ex(["12.5", "abc"], [12.5, None]))

simple("type.to_integer", "To whole number", CATEGORY,
       "Read as a whole number, dropping any fraction.", "to_integer",
       accepts=Accepts.ANY, synonyms=("to int", "integer", "whole"),
       example=_ex(["12.7", "abc"], [12, None]))

simple("type.to_boolean", "To true/false", CATEGORY,
       "Read yes/no/1/0/true/false. Anything else becomes null.", "to_boolean",
       accepts=Accepts.ANY, synonyms=("to bool", "yes no", "flag"),
       example=_ex(["yes", "0", "maybe"], [True, False, None]))

simple("type.detect", "Detect the type", CATEGORY,
       "Report what each value looks like, without changing it.", "detect_type",
       accepts=Accepts.ANY, synonyms=("what type", "guess type", "profile"),
       example=_ex(["12", "abc", "2026-01-01"], ["integer", "text", "timestamp"]))

simple("type.strip_currency", "Strip currency symbols", CATEGORY,
       "Remove symbols and grouping, leaving text a number parser can read.",
       "strip_currency",
       synonyms=("remove dollar", "currency", "money", "thousands separator"),
       params=(Param("style", "Written as", ParamKind.SELECT, default="us",
                     options=("us", "european"),
                     help="US: 1,234.56. European: 1.234,56."),),
       extra_args=lambda p: (lit(p["style"]),),
       example=Example(
           rows=({"value": "$1,200.50"}, {"value": "\u20ac1.200,50"}),
           params={"style": "us"},
           column="value",
           expect=("1200.50", "1.20050"),
           note="The second row shows why the style matters: read as US, a "
                "European amount comes out a thousand times too small.",
       ))

simple("type.parse_number_locale", "Parse a localised number", CATEGORY,
       "Read a number written with European or US grouping.", "parse_number_locale",
       synonyms=("comma decimal", "thousands separator", "european number"),
       params=(Param("style", "Written as", ParamKind.SELECT, default="us",
                     options=("us", "european"),
                     help="US: 1,234.56. European: 1.234,56."),),
       extra_args=lambda p: (lit(p["style"]),),
       example=_ex(["1.234,56"], [1234.56], {"style": "european"}))

simple("type.json_path", "Read a JSON field", CATEGORY,
       "Pull one value out of JSON by dotted path. Missing paths become null.",
       "parse_json_path",
       accepts=Accepts.ANY, synonyms=("json", "extract json", "nested field"),
       params=(Param("path", "Path", ParamKind.TEXT, placeholder="customer.id"),),
       extra_args=lambda p: (lit(p["path"]),),
       example=_ex(['{"customer": {"id": "C-1"}}', "{}"], ["C-1", None],
                   {"path": "customer.id"}))


def _cast(column, params):
    return Cast(value=column, to=parse_type(params["target"]))


custom("type.cast", "Change the type", CATEGORY,
       "Declare a column's type. Values that do not fit become null.", _cast,
       accepts=Accepts.ANY, synonyms=("convert", "retype", "change type"),
       params=(Param("target", "New type", ParamKind.SELECT, default="text",
                     options=CAST_TARGETS),),
       example=_ex(["12", "x"], [12, None], {"target": "int64"}))


def _coerce_with_fallback(column, params):
    # The fallback is for values that failed to parse, not for values that were
    # never there. A row that was empty stays empty.
    return null_safe(column, call("if_error", call("to_number", column), lit(params["fallback"])))


custom("type.coerce_with_fallback", "Convert with a fallback", CATEGORY,
       "Read as a number, using a fixed value where it will not parse.",
       _coerce_with_fallback,
       accepts=Accepts.ANY, synonyms=("default value", "on error", "safe convert"),
       params=(Param("fallback", "Use instead", ParamKind.TEXT, default="0"),),
       example=_ex(["12", "abc"], [12.0, "0"], {"fallback": "0"}))
