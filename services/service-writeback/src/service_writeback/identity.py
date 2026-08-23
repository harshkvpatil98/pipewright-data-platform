"""How a row is identified, which is the whole safety story of write-back.

An ``UPDATE`` whose ``WHERE`` clause does not identify exactly one row is a
data-loss bug waiting for its moment. Everything else in this service depends on
getting this right, so the preference order is explicit and there is no
fallback beyond the end of it:

1. **Declared primary key** -- use it.
2. **A unique constraint** (all columns NOT NULL) -- use it.
3. **A key the user designated**, re-validated for uniqueness against the live
   table *at commit time*, not when it was chosen.
4. **A physical row identifier** -- ``ctid``, ``rowid``, ``%%physloc%%``. Usable,
   but fragile across a vacuum or a table rewrite, so it is offered with that
   said plainly and only inside one short-lived session.
5. **Nothing** -- editing is refused, with an explanation and the offer to add a
   primary key.

There is deliberately no sixth option. "Match on all columns" is not offered,
because it silently updates every duplicate row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy import Engine, inspect, text

from shared_python.errors import BadRequestError


class IdentityKind(str, Enum):
    PRIMARY_KEY = "primary_key"
    UNIQUE_CONSTRAINT = "unique_constraint"
    DESIGNATED = "designated"
    PHYSICAL = "physical"
    NONE = "none"


#: The physical row identifier each dialect exposes, where one exists.
#: MySQL has none: InnoDB's internal row id is not selectable.
_PHYSICAL_COLUMN = {
    "postgresql": "ctid",
    "postgres": "ctid",
    "sqlite": "rowid",
    "duckdb": "rowid",
}

_PHYSICAL_CAVEAT = (
    "This is a physical row address, not a key. It changes when the database "
    "reorganises the table (a VACUUM, an OPTIMIZE, a restore), so it is only "
    "valid for as long as this editing session lasts. Adding a primary key is "
    "the durable fix."
)


@dataclass(frozen=True)
class RowIdentity:
    """How rows in one table are addressed."""

    kind: IdentityKind
    columns: tuple[str, ...] = ()
    #: Why this identity was chosen, or why none could be.
    reason: str = ""
    #: Shown prominently in the UI when the identity is not durable.
    caveat: str = ""

    @property
    def usable(self) -> bool:
        return self.kind is not IdentityKind.NONE

    @property
    def durable(self) -> bool:
        """False for identities that can change underneath us."""
        return self.kind in (IdentityKind.PRIMARY_KEY, IdentityKind.UNIQUE_CONSTRAINT)

    def require(self) -> tuple[str, ...]:
        if not self.usable:
            raise BadRequestError(self.reason)
        return self.columns


def resolve_identity(
    engine: Engine,
    *,
    table: str,
    schema: str | None = None,
    designated: list[str] | None = None,
    allow_physical: bool = False,
) -> RowIdentity:
    """Work out how to address a row in ``table``.

    ``designated`` is a key the user chose; it is accepted only if it is
    actually unique in the live table, checked here rather than trusted.
    """
    dialect = engine.dialect.name
    inspector = inspect(engine)

    try:
        columns = inspector.get_columns(table, schema=schema)
    except Exception as exc:
        raise BadRequestError(
            f"Could not read the structure of {table!r}: it does not exist, or "
            "this connection cannot see it."
        ) from exc

    if not columns:
        raise BadRequestError(f"Table {table!r} has no columns, or does not exist.")

    known = {str(column["name"]) for column in columns}
    not_null = {str(c["name"]) for c in columns if not c.get("nullable", True)}

    primary = inspector.get_pk_constraint(table, schema=schema) or {}
    pk_columns = [str(name) for name in (primary.get("constrained_columns") or [])]
    if pk_columns:
        return RowIdentity(
            IdentityKind.PRIMARY_KEY,
            tuple(pk_columns),
            reason=f"{table} has a primary key on {', '.join(pk_columns)}.",
        )

    for unique in inspector.get_unique_constraints(table, schema=schema) or []:
        names = [str(name) for name in (unique.get("column_names") or [])]
        # A unique constraint over a nullable column does not identify a row:
        # SQL treats NULLs as distinct, so several rows may hold NULL there.
        if names and all(name in not_null for name in names):
            return RowIdentity(
                IdentityKind.UNIQUE_CONSTRAINT,
                tuple(names),
                reason=(
                    f"{table} has no primary key, but a unique constraint on "
                    f"{', '.join(names)} identifies a row."
                ),
            )

    if designated:
        missing = [name for name in designated if name not in known]
        if missing:
            raise BadRequestError(
                f"Column(s) {', '.join(missing)} are not in {table}, so they cannot "
                "identify a row."
            )
        verify_designated_key(engine, table=table, schema=schema, columns=designated)
        return RowIdentity(
            IdentityKind.DESIGNATED,
            tuple(designated),
            reason=(
                f"{', '.join(designated)} was chosen as the key and is unique in "
                f"{table} right now."
            ),
            caveat=(
                "Nothing stops a duplicate being inserted later, because this is "
                "a choice rather than a constraint. It is re-checked before every "
                "commit."
            ),
        )

    physical = _PHYSICAL_COLUMN.get(dialect)
    if physical and allow_physical:
        return RowIdentity(
            IdentityKind.PHYSICAL,
            (physical,),
            reason=f"{table} has no key, so rows are addressed by {physical}.",
            caveat=_PHYSICAL_CAVEAT,
        )

    hint = (
        f" {dialect} exposes '{physical}' as a physical row address, which can be "
        "used for a single session if you accept that it is not stable."
        if physical
        else ""
    )
    return RowIdentity(
        IdentityKind.NONE,
        (),
        reason=(
            f"{table} has no primary key and no usable unique constraint, so there "
            "is no way to say which row an edit applies to. Add a primary key, or "
            f"choose columns that uniquely identify a row.{hint}"
        ),
    )


def verify_designated_key(
    engine: Engine, *, table: str, schema: str | None, columns: list[str]
) -> None:
    """Confirm a chosen key is actually unique, and has no nulls.

    Run at commit time as well as at choosing time: a key that was unique an
    hour ago is not a constraint, and an edit written against a duplicated key
    updates every copy.
    """
    if not columns:
        raise BadRequestError("A designated key needs at least one column.")

    quoted_table = _qualified(engine, table, schema)
    quoted = ", ".join(_quote(engine, name) for name in columns)
    null_check = " OR ".join(f"{_quote(engine, name)} IS NULL" for name in columns)

    with engine.connect() as connection:
        nulls = connection.execute(
            text(f"SELECT COUNT(*) FROM {quoted_table} WHERE {null_check}")
        ).scalar_one()
        if nulls:
            raise BadRequestError(
                f"{', '.join(columns)} cannot identify a row: {nulls:,} row(s) have "
                "no value there, and SQL treats every NULL as distinct."
            )

        duplicates = connection.execute(
            text(
                f"SELECT COUNT(*) FROM (SELECT {quoted} FROM {quoted_table} "
                f"GROUP BY {quoted} HAVING COUNT(*) > 1) AS d"
            )
        ).scalar_one()
        if duplicates:
            raise BadRequestError(
                f"{', '.join(columns)} cannot identify a row: {duplicates:,} value(s) "
                "appear more than once. An edit would change every copy."
            )


def _quote(engine: Engine, identifier: str) -> str:
    return engine.dialect.identifier_preparer.quote(identifier)


def _qualified(engine: Engine, table: str, schema: str | None) -> str:
    if schema:
        return f"{_quote(engine, schema)}.{_quote(engine, table)}"
    return _quote(engine, table)


@dataclass(frozen=True)
class TableShape:
    """What the compiler needs to know about a table, read once."""

    table: str
    schema: str | None
    columns: tuple[str, ...]
    nullable: frozenset[str]
    types: dict[str, Any] = field(default_factory=dict)
    identity: RowIdentity = field(default_factory=lambda: RowIdentity(IdentityKind.NONE))

    def require_columns(self, names: list[str]) -> None:
        unknown = [name for name in names if name not in self.columns]
        if unknown:
            raise BadRequestError(
                f"Column(s) {', '.join(unknown)} are not in {self.table}. "
                f"Available: {', '.join(self.columns)}"
            )


def read_shape(
    engine: Engine,
    *,
    table: str,
    schema: str | None = None,
    designated: list[str] | None = None,
    allow_physical: bool = False,
) -> TableShape:
    inspector = inspect(engine)
    try:
        columns = inspector.get_columns(table, schema=schema)
    except Exception as exc:
        # A driver exception reaching the API tells the caller nothing they can
        # act on, and leaks the shape of the backend into an error message.
        raise BadRequestError(
            f"Could not read the structure of {table!r}: it does not exist, or "
            "this connection cannot see it."
        ) from exc
    if not columns:
        raise BadRequestError(f"Table {table!r} has no columns, or does not exist.")
    return TableShape(
        table=table,
        schema=schema,
        columns=tuple(str(column["name"]) for column in columns),
        nullable=frozenset(str(c["name"]) for c in columns if c.get("nullable", True)),
        types={str(c["name"]): c.get("type") for c in columns},
        identity=resolve_identity(
            engine,
            table=table,
            schema=schema,
            designated=designated,
            allow_physical=allow_physical,
        ),
    )
