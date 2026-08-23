"""Tools for missing data.

The distinction this category exists to keep straight: an empty string is a
value somebody typed, and NULL is the absence of one. Conflating them is how a
count of "customers with no phone number" comes out wrong in both directions.
"""

from __future__ import annotations

from service_transformations.ir.expressions import Case, Column
from service_transformations.tools.builders import call, text as lit
from service_transformations.tools.declare import Accepts, Example, Param, ParamKind, custom, simple

CATEGORY = "Missing data"


def _ex(rows, expect, params=None):
    return Example(
        rows=tuple({"value": row} for row in rows),
        expect=tuple(expect),
        params=params or {},
        column="value",
    )


def _fill_constant(column, params):
    return call("coalesce", column, lit(params["value"]))


custom("null.fill_constant", "Fill blanks with a value", CATEGORY,
       "Replace nulls with a fixed value.", _fill_constant,
       accepts=Accepts.ANY, synonyms=("fill na", "replace null", "default"),
       params=(Param("value", "Value", ParamKind.TEXT, default=""),),
       example=_ex(["a", None], ["a", "unknown"], {"value": "unknown"}))


def _fill_from_column(column, params):
    return call("coalesce", column, Column(params["other"]))


custom("null.fill_from_column", "Fill blanks from another column", CATEGORY,
       "Where this column is null, take the value from another.", _fill_from_column,
       accepts=Accepts.ANY, synonyms=("coalesce", "fallback column"),
       params=(Param("other", "Other column", ParamKind.COLUMN),),
       example=Example(
           rows=({"value": "a", "backup": "x"}, {"value": None, "backup": "y"}),
           params={"other": "backup"},
           column="value",
           expect=("a", "y"),
       ))


def _empty_to_null(column, params):
    return Case(branches=((call("is_blank", column), call("nullif", column, column)),),
                default=column)


custom("null.empty_to_null", "Treat blanks as missing", CATEGORY,
       "Turn empty and whitespace-only text into a real null.", _empty_to_null,
       synonyms=("empty string", "blank to null"),
       example=_ex(["a", "   ", ""], ["a", None, None]))


def _null_to_empty(column, params):
    return call("coalesce", column, lit(""))


custom("null.null_to_empty", "Treat missing as blank", CATEGORY,
       "Turn nulls into empty text, for systems that cannot express null.",
       _null_to_empty,
       accepts=Accepts.ANY, synonyms=("null to empty string",),
       example=_ex(["a", None], ["a", ""]))


simple("null.normalise_tokens", "Recognise 'NA' as missing", CATEGORY,
       "Turn the strings exports use for nothing -- NA, N/A, NULL, -, unknown -- into real nulls.",
       "normalise_null_tokens",
       synonyms=("na", "n/a", "placeholder", "sentinel"),
       params=(Param("extra", "Also treat as missing", ParamKind.TEXT, required=False,
                     default="", placeholder="TBD, pending",
                     help="A comma-separated list, on top of the built-in ones."),),
       extra_args=lambda p: (lit(p["extra"] or ""),),
       example=_ex(["a", "N/A", "TBD"], ["a", None, None], {"extra": "TBD"}))


simple("null.is_blank", "Flag blanks", CATEGORY,
       "True where the value is missing or only whitespace.", "is_blank",
       accepts=Accepts.ANY, synonyms=("flag nulls", "is empty", "missing"),
       example=_ex(["a", None, "  "], [False, True, True]))
