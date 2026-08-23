"""Row operations."""

from __future__ import annotations

from shared_python.errors import BadRequestError
from shared_python.types import Kind, STRING

from service_transformations.ir.expressions import Call, Column, Literal
from service_transformations.ir.nodes import Distinct, Filter, Limit, Node, Sort, SortKey
from service_transformations.tools.builders import call, require_column
from service_transformations.tools.declare import Example, Param, ParamKind, frame

CATEGORY = "Rows"

_OPERATORS = {
    "equals": "eq",
    "not equals": "ne",
    "greater than": "gt",
    "at least": "ge",
    "less than": "lt",
    "at most": "le",
    "contains": "contains",
    "starts with": "starts_with",
    "ends with": "ends_with",
    "is empty": "is_blank",
    "is not empty": "is_blank",
}


_TRUE = {"true", "t", "yes", "y", "1", "on"}
_FALSE = {"false", "f", "no", "n", "0", "off"}


def _typed_literal(node: Node, column: str, raw: str):
    """Compare against a value of the column's own type where possible.

    Comparing a number column to the string "10", or a true/false column to the
    string "True", is the classic reason a filter returns nothing and nobody can
    see why -- the comparison is perfectly valid and simply never true.
    """
    from shared_python.types import BOOLEAN, FLOAT64, INT64

    kind = node.schema().get(column)
    if kind is None:
        return Literal(str(raw), STRING)

    if kind.kind is Kind.BOOLEAN:
        token = str(raw).strip().lower()
        if token in _TRUE:
            return Literal(True, BOOLEAN)
        if token in _FALSE:
            return Literal(False, BOOLEAN)
        raise BadRequestError(
            f"{column!r} holds true/false values, so {raw!r} cannot be compared "
            "with it. Use true or false."
        )

    if kind.is_numeric:
        try:
            if kind.is_integer:
                return Literal(int(raw), INT64)
            return Literal(float(raw), FLOAT64)
        except (TypeError, ValueError):
            raise BadRequestError(
                f"{column!r} holds numbers, so {raw!r} cannot be compared with it."
            ) from None

    return Literal(str(raw), STRING)


def _filter(node: Node, params: dict) -> Node:
    column = require_column(node, params["column"])
    operator = params["operator"]
    function = _OPERATORS[operator]

    if operator in ("is empty", "is not empty"):
        predicate = call("is_blank", Column(column))
        if operator == "is not empty":
            predicate = call("not", predicate)
    else:
        predicate = Call(function, (Column(column), _typed_literal(node, column, params["value"])))

    if params["mode"] == "exclude":
        # `not` on a null predicate stays null, and Filter drops nulls -- so an
        # exclusion would silently also drop rows where the test was unknown.
        # Coalescing to false first keeps "everything the filter did not match".
        predicate = call("not", call("coalesce", predicate, Literal(False, __import__(
            "shared_python.types", fromlist=["BOOLEAN"]).BOOLEAN)))
    return Filter(input=node, predicate=predicate)


frame("rows.filter", "Keep or drop matching rows", CATEGORY,
      "Keep only the rows a test matches, or drop them.", _filter,
      synonyms=("filter", "where", "exclude", "remove rows"),
      params=(
          Param("column", "Column", ParamKind.COLUMN),
          Param("operator", "Test", ParamKind.SELECT, default="equals",
                options=tuple(_OPERATORS)),
          Param("value", "Value", ParamKind.TEXT, required=False, default=""),
          Param("mode", "Then", ParamKind.SELECT, default="keep", options=("keep", "exclude")),
      ),
      example=Example(
          rows=({"region": "eu"}, {"region": "us"}, {"region": None}),
          params={"column": "region", "operator": "equals", "value": "eu", "mode": "keep"},
          output="region",
          expect=("eu",),
      ))


def _keep_top(node: Node, params: dict) -> Node:
    return Limit(input=node, count=int(params["count"]))


frame("rows.keep_top", "Keep the first rows", CATEGORY,
      "Keep the first N rows in the dataset's current order.", _keep_top,
      synonyms=("top n", "head", "limit", "first rows"),
      params=(Param("count", "How many", ParamKind.INTEGER, default=100, minimum=0, maximum=10_000_000),),
      example=Example(
          rows=({"n": 1}, {"n": 2}, {"n": 3}),
          params={"count": 2},
          output="n",
          expect=(1, 2),
      ))


def _skip(node: Node, params: dict) -> Node:
    return Limit(input=node, count=None, offset=int(params["count"]))


frame("rows.skip", "Skip the first rows", CATEGORY,
      "Drop the first N rows -- the usual fix for a file with a banner above the data.",
      _skip,
      synonyms=("offset", "drop first", "skip header"),
      params=(Param("count", "How many", ParamKind.INTEGER, default=1, minimum=0, maximum=10_000_000),),
      example=Example(
          rows=({"n": 1}, {"n": 2}, {"n": 3}),
          params={"count": 1},
          output="n",
          expect=(2, 3),
      ))


def _keep_range(node: Node, params: dict) -> Node:
    return Limit(input=node, count=int(params["count"]), offset=int(params["start"]))


frame("rows.keep_range", "Keep a range of rows", CATEGORY,
      "Keep N rows starting from a position, counting from zero.", _keep_range,
      synonyms=("slice rows", "page", "middle"),
      params=(
          Param("start", "Start at row", ParamKind.INTEGER, default=0, minimum=0, maximum=10_000_000),
          Param("count", "How many", ParamKind.INTEGER, default=10, minimum=0, maximum=10_000_000),
      ),
      example=Example(
          rows=({"n": 1}, {"n": 2}, {"n": 3}, {"n": 4}),
          params={"start": 1, "count": 2},
          output="n",
          expect=(2, 3),
      ))


def _sort(node: Node, params: dict) -> Node:
    columns = params["columns"]
    for name in columns:
        require_column(node, name)
    direction = "desc" if params["descending"] else "asc"
    keys = tuple(
        SortKey(expr=Column(name), direction=direction, nulls_first=bool(params["nulls_first"]))
        for name in columns
    )
    return Sort(input=node, keys=keys)


frame("rows.sort", "Sort rows", CATEGORY,
      "Order by one or more columns. Where nulls go is stated, not left to the engine.",
      _sort,
      synonyms=("order by", "sort", "arrange", "rank"),
      params=(
          Param("columns", "Sort by", ParamKind.COLUMNS),
          Param("descending", "Largest first", ParamKind.BOOLEAN, required=False, default=False),
          Param("nulls_first", "Blanks first", ParamKind.BOOLEAN, required=False, default=False),
      ),
      example=Example(
          rows=({"n": 3}, {"n": 1}, {"n": 2}),
          params={"columns": ["n"], "descending": False, "nulls_first": False},
          output="n",
          expect=(1, 2, 3),
      ))


def _deduplicate(node: Node, params: dict) -> Node:
    subset = tuple(params["columns"] or ())
    for name in subset:
        require_column(node, name)
    return Distinct(input=node, subset=subset, keep=params["keep"])


frame("rows.deduplicate", "Remove duplicate rows", CATEGORY,
      "Keep one row per distinct combination -- of every column, or of the ones you name.",
      _deduplicate,
      synonyms=("dedupe", "distinct", "unique", "remove duplicates"),
      params=(
          Param("columns", "Compare only these columns", ParamKind.COLUMNS, required=False,
                default=[], help="Leave empty to compare whole rows."),
          Param("keep", "Which to keep", ParamKind.SELECT, default="first",
                options=("first", "last")),
      ),
      example=Example(
          rows=({"n": 1}, {"n": 1}, {"n": 2}),
          params={"columns": [], "keep": "first"},
          output="n",
          expect=(1, 2),
      ))


def _drop_blank_rows(node: Node, params: dict) -> Node:
    """Drop rows that are blank in every named column, or in all of them."""
    columns = params["columns"] or list(node.schema())
    for name in columns:
        require_column(node, name)
    if not columns:
        raise BadRequestError("There are no columns to test.")

    filled = [call("not", call("is_blank", Column(name))) for name in columns]
    if params["mode"] == "any":
        predicate = filled[0]
        for part in filled[1:]:
            predicate = call("and", predicate, part)
    else:
        predicate = filled[0]
        for part in filled[1:]:
            predicate = call("or", predicate, part)
    return Filter(input=node, predicate=predicate)


frame("rows.drop_blank", "Drop blank rows", CATEGORY,
      "Remove rows that are empty -- in every column, or in any of the ones you name.",
      _drop_blank_rows,
      synonyms=("remove empty", "drop nulls", "blank rows"),
      params=(
          Param("columns", "Look at these columns", ParamKind.COLUMNS, required=False, default=[],
                help="Leave empty to look at every column."),
          Param("mode", "Drop when", ParamKind.SELECT, default="all",
                options=("all", "any"),
                help="'all': every named column is blank. 'any': at least one is."),
      ),
      example=Example(
          rows=({"a": "x", "b": "y"}, {"a": None, "b": None}, {"a": "z", "b": None}),
          params={"columns": [], "mode": "all"},
          output="a",
          expect=("x", "z"),
      ))
