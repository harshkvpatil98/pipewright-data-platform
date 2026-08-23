"""Validation and assertion tools.

Two shapes, and the difference matters:

* **Flags** add a column saying whether each row passed. The run continues, and
  the failures are countable and inspectable.
* **Quarantine** splits the failures out of the frame.

Neither of them stops a run. Failing a pipeline on a data problem is a *quality
gate*, which the workflow engine already has and which belongs at a run boundary
rather than in the middle of a recipe -- putting it here would give two ways to
express the same rule that behave differently.
"""

from __future__ import annotations

from shared_python.types import BOOLEAN, STRING

from service_transformations.ir.expressions import Call, Column, Literal
from service_transformations.ir.nodes import Filter, Node
from service_transformations.tools.builders import call, integer, number, require_column, text as lit
from service_transformations.tools.declare import (
    Accepts,
    Example,
    Param,
    ParamKind,
    custom,
    frame,
    simple,
)

CATEGORY = "Validation"


def _ex(rows, expect, params=None):
    return Example(
        rows=tuple({"value": row} for row in rows),
        expect=tuple(expect),
        params=params or {},
        column="value",
    )


simple("check.is_email", "Looks like an email", CATEGORY,
       "True for text shaped like an email address.", "is_email",
       synonyms=("validate email", "email check"),
       example=_ex(["a@b.com", "nope"], [True, False]))

simple("check.is_url", "Looks like a URL", CATEGORY,
       "True for text shaped like an http or https URL.", "is_url",
       synonyms=("validate url",),
       example=_ex(["https://a.co", "a.co"], [True, False]))

simple("check.is_date", "Reads as a date", CATEGORY,
       "True where the value can be read as a date.", "is_date",
       accepts=Accepts.ANY, synonyms=("validate date", "parseable date"),
       example=_ex(["2026-01-01", "nope"], [True, False]))

simple("check.is_number", "Reads as a number", CATEGORY,
       "True where the value can be read as a number.", "is_number",
       accepts=Accepts.ANY, synonyms=("validate number", "numeric check"),
       example=_ex(["12", "abc"], [True, False]))

simple("check.in_range", "Within a range", CATEGORY,
       "True where a number falls between two bounds, inclusive.", "in_range",
       accepts=Accepts.NUMERIC, synonyms=("between", "bounds", "range check"),
       params=(
           Param("minimum", "At least", ParamKind.NUMBER, default=0),
           Param("maximum", "At most", ParamKind.NUMBER, default=100),
       ),
       extra_args=lambda p: (number(p["minimum"]), number(p["maximum"])),
       example=_ex([5, 500], [True, False], {"minimum": 0, "maximum": 100}))

simple("check.matches_pattern", "Matches a pattern", CATEGORY,
       "True where a regular expression matches.", "regex_match",
       synonyms=("regex check", "format check"),
       params=(Param("pattern", "Pattern", ParamKind.TEXT, placeholder=r"^[A-Z]{2}-\d+$"),),
       extra_args=lambda p: (lit(p["pattern"]),),
       example=_ex(["AB-1", "x"], [True, False], {"pattern": r"^[A-Z]{2}-\d+$"}))


def _length_between(column, params):
    length = call("length", column)
    return call("and",
                call("ge", length, integer(int(params["minimum"]))),
                call("le", length, integer(int(params["maximum"]))))


custom("check.length_between", "Length within bounds", CATEGORY,
       "True where the text's length falls between two bounds.", _length_between,
       synonyms=("length check", "too long", "too short"),
       params=(
           Param("minimum", "At least", ParamKind.INTEGER, default=0, minimum=0, maximum=1_000_000),
           Param("maximum", "At most", ParamKind.INTEGER, default=255, minimum=0, maximum=1_000_000),
       ),
       example=_ex(["abc", "abcdefgh"], [True, False], {"minimum": 1, "maximum": 5}))


def _in_set(column, params):
    allowed = [Literal(str(value), STRING) for value in params["values"]]
    return Call("in_list", (call("to_text", column), *allowed))


custom("check.in_set", "One of a list", CATEGORY,
       "True where the value is one of an allowed list.", _in_set,
       accepts=Accepts.ANY, synonyms=("allowed values", "enum", "whitelist", "domain"),
       params=(Param("values", "Allowed values", ParamKind.LIST,
                     help="One per line."),),
       example=_ex(["eu", "mars"], [True, False], {"values": ["eu", "us"]}))


def _quarantine(node: Node, params: dict) -> Node:
    """Split failures out of the frame, keeping whichever side was asked for."""
    column = require_column(node, params["column"])
    passing = Column(column)
    if params["keep"] == "failures":
        # Rows where the flag is null failed too: an unknown result is not a pass.
        return Filter(input=node, predicate=call(
            "not", call("coalesce", passing, Literal(False, BOOLEAN))
        ))
    return Filter(input=node, predicate=passing)


frame("check.quarantine", "Split on a check column", CATEGORY,
      "Keep only the rows that passed a check, or only the ones that failed.",
      _quarantine,
      synonyms=("quarantine", "split failures", "bad rows", "reject"),
      params=(
          Param("column", "Check column", ParamKind.COLUMN,
                help="A true/false column produced by one of the checks above."),
          Param("keep", "Keep", ParamKind.SELECT, default="passes",
                options=("passes", "failures")),
      ),
      example=Example(
          rows=({"ok": True, "id": 1}, {"ok": False, "id": 2}, {"ok": None, "id": 3}),
          params={"column": "ok", "keep": "failures"},
          output="id",
          expect=(2, 3),
      ))
