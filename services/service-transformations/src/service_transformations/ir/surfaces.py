"""What a source can execute for itself.

Pushdown only works if we know what the far end can actually do. This is the
same discipline as connector capabilities in Phase 04: a surface describes what
works *here*, not what the engine is documented to support, and a dialect that
cannot express something says so rather than being handed SQL it will
misinterpret.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Surface(str, Enum):
    """How much of the algebra a source can run."""

    #: A real SQL database: everything except Extension nodes.
    SQL_FULL = "sql_full"
    #: SQL-ish, but missing pieces -- older MySQL has no CTEs or window functions.
    SQL_LIMITED = "sql_limited"
    #: Filtering and limiting via query parameters only. Most REST SaaS.
    QUERY_API = "query_api"
    #: Predicate and projection pushdown into the file format. Parquet, ORC.
    COLUMNAR_FILE = "columnar_file"
    #: Read it all and transform locally. CSV, JSON, most APIs.
    NONE = "none"


@dataclass(frozen=True)
class SourceSurface:
    """A source's execution capabilities, declared rather than assumed."""

    name: str
    surface: Surface
    #: The SQL dialect to compile for, when the surface is SQL.
    dialect: str | None = None
    #: Node kinds this source can run. Checked before anything is compiled, so
    #: an unsupported node stops the prefix rather than producing bad SQL.
    supports_filter: bool = False
    supports_project: bool = False
    supports_aggregate: bool = False
    supports_join: bool = False
    supports_sort: bool = False
    supports_limit: bool = False
    supports_distinct: bool = False
    supports_set_ops: bool = False
    #: Why this source cannot do more, in words a person can act on.
    note: str = ""

    @property
    def is_sql(self) -> bool:
        return self.surface in (Surface.SQL_FULL, Surface.SQL_LIMITED)

    def supports(self, node_kind: str) -> bool:
        return bool(getattr(self, f"supports_{node_kind}", False))


def sql_surface(name: str, dialect: str, *, full: bool = True, note: str = "") -> SourceSurface:
    return SourceSurface(
        name=name,
        surface=Surface.SQL_FULL if full else Surface.SQL_LIMITED,
        dialect=dialect,
        supports_filter=True,
        supports_project=True,
        supports_aggregate=True,
        supports_join=True,
        supports_sort=True,
        supports_limit=True,
        supports_distinct=True,
        supports_set_ops=full,
        note=note,
    )


#: Surfaces for the sources that exist today. A source absent from here gets
#: `LOCAL_ONLY`, which is the safe answer: everything runs locally and nothing
#: is silently assumed to work.
_SURFACES: dict[str, SourceSurface] = {
    "postgresql": sql_surface("postgresql", "postgres"),
    "postgres": sql_surface("postgres", "postgres"),
    "mysql": sql_surface(
        "mysql",
        "mysql",
        full=False,
        note="No INTERSECT or EXCEPT before 8.0.31, and no DISTINCT ON at all.",
    ),
    "sqlite": sql_surface(
        "sqlite",
        "sqlite",
        full=True,
        note="No FULL OUTER JOIN, and no DISTINCT ON.",
    ),
    "duckdb": sql_surface("duckdb", "duckdb"),
}

LOCAL_ONLY = SourceSurface(
    name="local",
    surface=Surface.NONE,
    note="This source hands over rows and nothing else; every step runs here.",
)

#: File formats that can at least skip columns and rows before we read them.
COLUMNAR = SourceSurface(
    name="columnar_file",
    surface=Surface.COLUMNAR_FILE,
    supports_filter=True,
    supports_project=True,
    note="Parquet and ORC can skip row groups and columns, but cannot join or group.",
)

#: Most REST SaaS: a `filter` and a `limit` query parameter, and nothing else.
QUERY_API = SourceSurface(
    name="query_api",
    surface=Surface.QUERY_API,
    supports_filter=True,
    supports_limit=True,
    note="Filtering and limiting happen server-side; everything else runs here.",
)


def surface_for(source_type: str | None) -> SourceSurface:
    """The surface for a connector type. Unknown sources run locally."""
    if not source_type:
        return LOCAL_ONLY
    return _SURFACES.get(source_type.strip().lower(), LOCAL_ONLY)


def register_surface(surface: SourceSurface) -> SourceSurface:
    _SURFACES[surface.name.lower()] = surface
    return surface


def known_surfaces() -> list[str]:
    return sorted(_SURFACES)
