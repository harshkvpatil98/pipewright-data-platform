"""Date macros for workflow node configuration.

A node's configuration can reference the run's *logical date* rather than a
hard-coded value, so the same workflow means "yesterday's orders" whether it
runs on schedule tonight or as part of a backfill over last March.

    table_name: "orders_{{ ds }}"
    message:    "Loaded {{ yesterday }} through {{ ds }}"
    query:      "... WHERE day >= '{{ ds_sub(7) }}'"

The logical date is the slot a run represents, not the moment it executed. A
backfill slot for 3 March resolves ``{{ ds }}`` to 2026-03-03 even though it
runs today, which is what makes a backfill reproduce the original run.

Unknown macros raise rather than passing through: a typo silently left in a
table name would create the wrong table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from shared_python.errors import BadRequestError

# {{ token }} with flexible inner whitespace.
MACRO_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

# ds_add(3) / ds_sub(7)
OFFSET_PATTERN = re.compile(r"^(ds_add|ds_sub)\(\s*(-?\d{1,5})\s*\)$")

PARAM_PREFIX = "params."


@dataclass(frozen=True)
class MacroContext:
    """Everything a macro can resolve against."""

    logical_date: datetime
    run_started_at: datetime
    workflow_name: str = ""
    parameters: dict[str, Any] | None = None

    @classmethod
    def for_run(
        cls,
        *,
        logical_date: datetime | None,
        workflow_name: str = "",
        parameters: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> MacroContext:
        started = now or datetime.now(UTC)
        # A manual run has no slot of its own, so it stands for the present.
        moment = logical_date or started
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return cls(
            logical_date=moment,
            run_started_at=started,
            workflow_name=workflow_name,
            parameters=parameters or {},
        )


def _simple_values(context: MacroContext) -> dict[str, str]:
    day = context.logical_date
    return {
        "ds": day.strftime("%Y-%m-%d"),
        "run_date": day.strftime("%Y-%m-%d"),
        "yesterday": (day - timedelta(days=1)).strftime("%Y-%m-%d"),
        "tomorrow": (day + timedelta(days=1)).strftime("%Y-%m-%d"),
        "ds_nodash": day.strftime("%Y%m%d"),
        "run_ts": day.isoformat(),
        "year": day.strftime("%Y"),
        "month": day.strftime("%m"),
        "day": day.strftime("%d"),
        "hour": day.strftime("%H"),
        "month_start": day.replace(day=1).strftime("%Y-%m-%d"),
        "executed_at": context.run_started_at.isoformat(),
        "workflow_name": context.workflow_name,
    }


AVAILABLE_MACROS: tuple[str, ...] = (
    "ds",
    "run_date",
    "yesterday",
    "tomorrow",
    "ds_nodash",
    "run_ts",
    "year",
    "month",
    "day",
    "hour",
    "month_start",
    "executed_at",
    "workflow_name",
    "ds_add(n)",
    "ds_sub(n)",
    "params.<name>",
)


def resolve_token(token: str, context: MacroContext) -> str:
    """Resolve one macro token to its string value."""
    name = token.strip()

    simple = _simple_values(context)
    if name in simple:
        return simple[name]

    offset = OFFSET_PATTERN.match(name)
    if offset:
        direction, amount = offset.group(1), int(offset.group(2))
        days = amount if direction == "ds_add" else -amount
        return (context.logical_date + timedelta(days=days)).strftime("%Y-%m-%d")

    if name.startswith(PARAM_PREFIX):
        key = name[len(PARAM_PREFIX) :].strip()
        parameters = context.parameters or {}
        if key not in parameters:
            available = ", ".join(sorted(parameters)) or "none"
            raise BadRequestError(
                f"This run has no parameter '{key}' (available: {available})."
            )
        return str(parameters[key])

    raise BadRequestError(
        f"Unknown macro '{{{{ {name} }}}}'. Available: {', '.join(AVAILABLE_MACROS)}."
    )


def render(value: str, context: MacroContext) -> str:
    """Substitute every macro in a single string."""
    return MACRO_PATTERN.sub(lambda match: resolve_token(match.group(1), context), value)


def contains_macro(value: Any) -> bool:
    """True when a value (or anything nested in it) references a macro."""
    if isinstance(value, str):
        return bool(MACRO_PATTERN.search(value))
    if isinstance(value, dict):
        return any(contains_macro(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_macro(item) for item in value)
    return False


def resolve_config(config: Any, context: MacroContext) -> Any:
    """Recursively resolve macros through a node's configuration.

    Only strings are touched; numbers, booleans, and nulls pass through
    unchanged so a config's shape is never altered by rendering.
    """
    if isinstance(config, str):
        return render(config, context)
    if isinstance(config, dict):
        return {key: resolve_config(item, context) for key, item in config.items()}
    if isinstance(config, list):
        return [resolve_config(item, context) for item in config]
    return config


def describe(context: MacroContext) -> dict[str, str]:
    """The resolved value of every simple macro, for display and for the run record."""
    return _simple_values(context)
