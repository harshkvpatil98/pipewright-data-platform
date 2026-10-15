"""What is known about a table's values, for estimating row counts (D2, O1).

One shape for every source of statistics: a dataset version (computed from
every row when it is written, in its profile), a table in a connected
database (from the database's own statistics, or a sample), and anything
else that can say how many rows it has. The estimator (`ir/estimate.py`)
reads only this, so it never learns where the numbers came from; each
carries `method` so a plan can say.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ColumnStats:
    name: str
    #: number, datetime, text, boolean or empty.
    kind: str = "text"
    #: Share of rows with no value, 0 to 1.
    empty_share: float = 0.0
    #: Distinct values among those that have one; None when unknown.
    distinct: int | None = None
    lowest: Any = None
    highest: Any = None
    #: Equal-count bucket edges (numbers; dates as milliseconds since 1970) and rows in each.
    bounds: list[float] = field(default_factory=list)
    bucket_rows: list[int] = field(default_factory=list)
    #: The commonest values as text, with how many rows have each.
    common: list[tuple[str, int]] = field(default_factory=list)
    #: True when the histogram leaves the commonest values out (PostgreSQL's
    #: does): a range then counts them separately. A profile's covers every value.
    histogram_excludes_common: bool = False


@dataclass
class TableStats:
    rows: int
    columns: dict[str, ColumnStats] = field(default_factory=dict)
    #: How the numbers were got, in words: "every row", "the database's own statistics", "a sample of 10,000 rows".
    method: str = "every row"
    collected_at: datetime | None = None

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["collected_at"] = self.collected_at.isoformat() if self.collected_at else None
        out["columns"] = {name: {**asdict(column), "common": [list(item) for item in column.common]}
                          for name, column in self.columns.items()}
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> TableStats | None:
        if not data:
            return None
        columns = {}
        for name, raw in (data.get("columns") or {}).items():
            columns[name] = ColumnStats(
                name=raw.get("name", name), kind=raw.get("kind", "text"),
                empty_share=float(raw.get("empty_share") or 0.0), distinct=raw.get("distinct"),
                lowest=raw.get("lowest"), highest=raw.get("highest"),
                bounds=list(raw.get("bounds") or []), bucket_rows=list(raw.get("bucket_rows") or []),
                common=[(str(v), int(n)) for v, n in raw.get("common") or []],
                histogram_excludes_common=bool(raw.get("histogram_excludes_common")),
            )
        collected = data.get("collected_at")
        return cls(rows=int(data.get("rows") or 0), columns=columns, method=str(data.get("method") or "every row"),
                   collected_at=datetime.fromisoformat(collected) if collected else None)


_KINDS = {"int": "number", "float": "number", "decimal": "number", "datetime": "datetime", "date": "datetime",
          "bool": "boolean", "empty": "empty"}


def from_profile(profile: dict[str, Any] | None, *, collected_at: datetime | None = None) -> TableStats | None:
    """A dataset version's statistics from the profile written with it."""
    if not profile:
        return None
    rows = int(profile.get("row_count") or 0)
    columns: dict[str, ColumnStats] = {}
    for entry in profile.get("columns") or []:
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        histogram = entry.get("histogram") or {}
        kind = _KINDS.get(str(entry.get("inferred_type")))
        if histogram.get("unit") == "epoch_ms":
            # Dates, whether held as dates or written as ISO text (which sorts the same way).
            kind = "datetime"
        elif kind is None:
            # A streamed profile infers no types; a histogram says what its column holds.
            kind = ("datetime" if histogram.get("unit") == "epoch_ms" else "number") if histogram else "text"
        columns[str(entry["name"])] = ColumnStats(
            name=str(entry["name"]),
            kind=kind,
            empty_share=float(entry.get("null_percentage") or 0.0) / 100.0,
            distinct=entry.get("unique_count"),
            lowest=entry.get("min_value"),
            highest=entry.get("max_value"),
            bounds=list(histogram.get("bounds") or []),
            bucket_rows=list(histogram.get("rows") or []),
            common=[(str(item["value"]), int(item["rows"])) for item in entry.get("common_values") or []
                    if isinstance(item, dict) and "value" in item],
        )
    return TableStats(rows=rows, columns=columns, method="every row", collected_at=collected_at)
