"""The edits a change set can hold, and the rules each one carries.

Edits are described, not executed. A change set is reviewable, diffable and
discardable precisely because nothing here touches a database -- compilation and
execution happen later, behind a dry run and an explicit commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from shared_python.errors import BadRequestError

#: Beyond this, a change is asked to be confirmed by typing the table name.
DEFAULT_BLAST_RADIUS = 1_000

#: And beyond this share of the table, regardless of the absolute number.
DEFAULT_BLAST_SHARE = 0.10

#: The share rule ignores changes smaller than this. A percentage of a small
#: table is not a risk signal: editing one row of a three-row lookup table is a
#: third of it, and asking somebody to type the table name for that trains them
#: to type it without reading. Below this count, only the absolute limit applies.
BLAST_SHARE_FLOOR_ROWS = 25


class _Unrecorded:
    """Marks a field nobody supplied, distinct from a supplied ``None``."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unrecorded>"

    def __bool__(self) -> bool:
        return False


_UNRECORDED = _Unrecorded()


class EditKind(str, Enum):
    SET_CELL = "set_cell"
    INSERT_ROW = "insert_row"
    DELETE_ROW = "delete_row"
    ADD_COLUMN = "add_column"
    DROP_COLUMN = "drop_column"
    RENAME_COLUMN = "rename_column"


#: Data changes and structure changes are ordered differently and permissioned
#: differently: adding a column before writing values into it is not optional.
DDL_KINDS = frozenset(
    {EditKind.ADD_COLUMN, EditKind.DROP_COLUMN, EditKind.RENAME_COLUMN}
)

#: Edits with no inverse. Surfaced prominently rather than discovered.
IRREVERSIBLE_KINDS = frozenset({EditKind.DELETE_ROW, EditKind.DROP_COLUMN})


@dataclass(frozen=True)
class Edit:
    """One staged change.

    ``key`` addresses the row for cell and delete edits, using whatever the
    table's identity resolved to. ``version`` is what the row looked like when
    it was read, and is how a concurrent change is detected.
    """

    kind: EditKind
    #: Row key values, by column. Empty for DDL and inserts.
    key: dict[str, Any] = field(default_factory=dict)
    column: str | None = None
    value: Any = None
    #: SET_CELL only, for the diff, for undo, and for detecting a concurrent
    #: change. Defaults to a sentinel rather than None, because None is a
    #: legitimate previous value and the two must not be confused.
    previous: Any = _UNRECORDED
    #: INSERT_ROW only.
    values: dict[str, Any] = field(default_factory=dict)
    #: ADD_COLUMN only: the SQL type to create.
    column_type: str | None = None
    #: RENAME_COLUMN only.
    new_name: str | None = None
    #: Hash of the row as read, for optimistic concurrency.
    version: str | None = None

    @property
    def is_noop(self) -> bool:
        """True when this edit would write the value the cell already holds.

        Only knowable when the edit recorded what it read; without that, the
        write has to happen, because "unchanged" is a claim nobody made.
        """
        return (
            self.kind is EditKind.SET_CELL
            and self.records_previous
            and _same_value(self.previous, self.value)
        )

    @property
    def records_previous(self) -> bool:
        """Whether this edit knows what it is replacing.

        A sentinel is needed because `None` is a legitimate previous value: a
        cell that was NULL and is being given a value must still be checked
        against NULL. `_UNRECORDED` distinguishes "was null" from "not read".
        """
        return self.previous is not _UNRECORDED

    @property
    def is_ddl(self) -> bool:
        return self.kind in DDL_KINDS

    @property
    def irreversible(self) -> bool:
        return self.kind in IRREVERSIBLE_KINDS

    def describe(self) -> str:
        """One line a person can check, for the review screen."""
        if self.kind is EditKind.SET_CELL:
            return f"set {self.column} = {self.value!r} where {_render_key(self.key)}"
        if self.kind is EditKind.DELETE_ROW:
            return f"delete row where {_render_key(self.key)}"
        if self.kind is EditKind.INSERT_ROW:
            return f"insert row {self.values!r}"
        if self.kind is EditKind.ADD_COLUMN:
            return f"add column {self.column} {self.column_type}"
        if self.kind is EditKind.DROP_COLUMN:
            return f"drop column {self.column}"
        if self.kind is EditKind.RENAME_COLUMN:
            return f"rename column {self.column} to {self.new_name}"
        return str(self.kind)


def _same_value(left: Any, right: Any) -> bool:
    """Would the database see these two as the same value?

    Deliberately loose across the string/number divide: a grid hands back "10"
    for a cell that came out of an integer column as 10, and treating that as a
    change would write every cell the cursor merely passed through.
    """
    if left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float, Decimal)) or isinstance(right, (int, float, Decimal)):
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except (InvalidOperation, ValueError):
            return str(left) == str(right)
    return left == right


def _render_key(key: dict[str, Any]) -> str:
    return " and ".join(f"{name}={value!r}" for name, value in sorted(key.items()))


def validate(edit: Edit, *, columns: tuple[str, ...], key_columns: tuple[str, ...]) -> None:
    """Check one edit against the table it targets.

    Run when the edit is staged and again before compiling: the table may have
    changed in between, and a change set is not a lock.
    """
    if edit.kind is EditKind.SET_CELL:
        if not edit.column:
            raise BadRequestError("A cell edit needs a column.")
        if edit.column not in columns:
            raise BadRequestError(f"Column {edit.column!r} is not in this table.")
        if edit.column in key_columns:
            # Changing the key is a delete plus an insert, which is a different
            # decision with different consequences.
            raise BadRequestError(
                f"{edit.column!r} identifies the row, so it cannot be edited in "
                "place. Delete the row and insert a replacement instead."
            )
        _require_key(edit, key_columns)

    elif edit.kind is EditKind.DELETE_ROW:
        _require_key(edit, key_columns)

    elif edit.kind is EditKind.INSERT_ROW:
        if not edit.values:
            raise BadRequestError("An inserted row needs at least one value.")
        unknown = [name for name in edit.values if name not in columns]
        if unknown:
            raise BadRequestError(
                f"Column(s) {', '.join(unknown)} are not in this table."
            )

    elif edit.kind is EditKind.ADD_COLUMN:
        if not edit.column:
            raise BadRequestError("A new column needs a name.")
        if edit.column in columns:
            raise BadRequestError(f"Column {edit.column!r} already exists.")
        if not edit.column_type:
            raise BadRequestError(f"Column {edit.column!r} needs a type.")

    elif edit.kind is EditKind.DROP_COLUMN:
        if edit.column not in columns:
            raise BadRequestError(f"Column {edit.column!r} is not in this table.")
        if edit.column in key_columns:
            raise BadRequestError(
                f"{edit.column!r} identifies rows in this table; dropping it would "
                "leave no way to address them."
            )

    elif edit.kind is EditKind.RENAME_COLUMN:
        if edit.column not in columns:
            raise BadRequestError(f"Column {edit.column!r} is not in this table.")
        if not edit.new_name:
            raise BadRequestError("A rename needs a new name.")
        if edit.new_name in columns:
            raise BadRequestError(f"Column {edit.new_name!r} already exists.")


def _require_key(edit: Edit, key_columns: tuple[str, ...]) -> None:
    if not key_columns:
        raise BadRequestError(
            "This table has no usable row key, so an edit cannot say which row "
            "it applies to."
        )
    missing = [name for name in key_columns if name not in edit.key]
    if missing:
        raise BadRequestError(
            f"This edit is missing key value(s): {', '.join(missing)}."
        )


def row_version(values: dict[str, Any], columns: tuple[str, ...]) -> str:
    """A stable fingerprint of a row as it was read.

    Used for optimistic concurrency where the table has no version column. The
    hash covers every column, so any change by anybody else is detected -- not
    only a change to the column being edited.
    """
    import hashlib

    parts = []
    for name in columns:
        value = values.get(name)
        # `None` and the string "None" must not collide, or a null and the word
        # would fingerprint identically.
        parts.append("\x00NULL\x00" if value is None else f"\x00{type(value).__name__}:{value}\x00")
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


def project_columns(
    columns: tuple[str, ...], edits: Iterable[Edit], *, apply_drops: bool = True
) -> tuple[str, ...]:
    """The columns the table will have once these edits are applied.

    Follows the compiler's order -- adds, then renames, then drops -- because
    that is the order the database will see, not the order they were staged in.

    ``apply_drops=False`` gives the column set that row edits run against: a
    change set may legitimately write to a column and then drop it, and the
    compiler puts every drop last precisely so that works.
    """
    working = list(columns)
    for edit in edits:
        if edit.kind is EditKind.ADD_COLUMN and edit.column:
            working.append(edit.column)
    for edit in edits:
        if edit.kind is EditKind.RENAME_COLUMN and edit.column and edit.new_name:
            working = [edit.new_name if name == edit.column else name for name in working]
    if apply_drops:
        dropped = {edit.column for edit in edits if edit.kind is EditKind.DROP_COLUMN}
        working = [name for name in working if name not in dropped]
    return tuple(working)


def validate_all(
    edits: Sequence[Edit], *, columns: tuple[str, ...], key_columns: tuple[str, ...]
) -> None:
    """Validate a whole change set against the shape it will actually run against.

    Checking each edit against the table as it is today makes the commonest
    Studio gesture impossible -- add a column, then type values into it -- because
    the column does not exist until the change set runs. Structure changes are
    therefore checked against the table as it accumulates, and row edits against
    the table as it will be once the structure changes have happened.
    """
    structure = [edit for edit in edits if edit.kind in DDL_KINDS]
    rows = [edit for edit in edits if edit.kind not in DDL_KINDS]

    # Renaming a key column would leave every other edit in this change set
    # addressing a column name that no longer exists by the time it runs.
    renamed_keys = [
        edit.column
        for edit in structure
        if edit.kind is EditKind.RENAME_COLUMN and edit.column in key_columns
    ]
    if renamed_keys and rows:
        raise BadRequestError(
            f"{renamed_keys[0]!r} identifies rows in this table. Rename it in a "
            "change set of its own, or the other edits here would no longer know "
            "which rows they mean."
        )

    # Structure, in compiler order, each against the table as it stands by then.
    seen: list[Edit] = []
    for kind in (EditKind.ADD_COLUMN, EditKind.RENAME_COLUMN, EditKind.DROP_COLUMN):
        for edit in (item for item in structure if item.kind is kind):
            validate(
                edit,
                columns=project_columns(columns, seen),
                key_columns=key_columns,
            )
            seen.append(edit)

    available = project_columns(columns, structure, apply_drops=False)
    for edit in rows:
        validate(edit, columns=available, key_columns=key_columns)
