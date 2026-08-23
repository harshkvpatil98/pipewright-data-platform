"""Reading the rows that are about to be edited.

Separate from the extraction service's preview on purpose. A preview is a
sample: it has no defined order, so scrolling it twice can show different rows
in the same place. An editing surface cannot work that way -- the row under the
cursor has to be the same row on the next page -- so these reads are ordered by
the same key the edits will address rows with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, text

from shared_python.errors import BadRequestError

from service_writeback.identity import TableShape

#: Reading more than this in one request is a report, not an editing session.
MAX_PAGE = 500


@dataclass
class RowPage:
    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    offset: int = 0
    #: The columns that address a row, repeated here so the client does not have
    #: to hold the shape response to build an edit.
    key_columns: list[str] = field(default_factory=list)


def read_rows(
    engine: Engine,
    shape: TableShape,
    *,
    limit: int = 100,
    offset: int = 0,
    order_by: str | None = None,
    descending: bool = False,
) -> RowPage:
    if limit < 1 or limit > MAX_PAGE:
        raise BadRequestError(f"Ask for between 1 and {MAX_PAGE} rows.")
    if offset < 0:
        raise BadRequestError("The offset cannot be negative.")

    quote = engine.dialect.identifier_preparer.quote
    qualified = f"{quote(shape.schema)}.{quote(shape.table)}" if shape.schema else quote(shape.table)

    ordering = list(shape.identity.columns)
    if order_by:
        if order_by not in shape.columns:
            raise BadRequestError(f"Column {order_by!r} is not in {shape.table}.")
        # The key stays in the ORDER BY as a tie-breaker: sorting by a column
        # with repeated values would otherwise leave paging non-deterministic,
        # which is the exact problem this function exists to avoid.
        ordering = [order_by, *[name for name in ordering if name != order_by]]
    if not ordering:
        raise BadRequestError(shape.identity.reason)

    direction = " DESC" if descending else ""
    order_sql = ", ".join(f"{quote(name)}{direction}" for name in ordering)
    selected = ", ".join(quote(name) for name in shape.columns)

    with engine.connect() as connection:
        total = int(connection.execute(text(f"SELECT COUNT(*) FROM {qualified}")).scalar_one())
        result = connection.execute(
            text(
                f"SELECT {selected} FROM {qualified} ORDER BY {order_sql} "
                "LIMIT :limit OFFSET :offset"
            ),
            {"limit": limit, "offset": offset},
        )
        rows = [dict(row) for row in result.mappings()]

    return RowPage(
        columns=list(shape.columns),
        rows=rows,
        total=total,
        offset=offset,
        key_columns=list(shape.identity.columns),
    )
