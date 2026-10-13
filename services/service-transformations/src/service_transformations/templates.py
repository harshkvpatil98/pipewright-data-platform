"""Recipe templates: common cleaning jobs as ready-made steps.

A person who knows what they want ("tidy this contact list") should not have
to know which five steps do it. A template names the columns it needs by role
-- "the email column", "the date to group by" -- matches those roles against a
dataset's columns by name and type, and produces ordinary recipe steps. The
steps are then edited, previewed and saved like any others; nothing here runs
or stores anything.

Every template is executed against data in `tests/test_templates.py`, so a
template that produces a step the engine rejects fails the build rather than
the person who chose it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from shared_python.errors import BadRequestError, NotFoundError

TEXT_TYPES = {"string", "text", "str", "object", "category"}
NUMBER_TYPES = {"int", "integer", "int64", "float", "float64", "number", "decimal", "double"}
DATE_TYPES = {"date", "datetime", "timestamp", "datetime64", "time"}


@dataclass(frozen=True)
class Role:
    """One column (or several) a template needs."""

    key: str
    label: str
    description: str
    #: "text", "number", "date" or "any".
    kind: str = "any"
    #: Words that suggest a column plays this role, matched against its name.
    hints: tuple[str, ...] = ()
    required: bool = True
    #: Several columns rather than one.
    multiple: bool = False


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str
    roles: tuple[Role, ...]
    #: (mapping, columns, types) -> steps.
    build: Callable[[Mapping[str, Any], Sequence[str], Mapping[str, str]], list[dict[str, Any]]] = field(
        repr=False
    )


def _kind_of(type_name: str | None) -> str:
    value = (type_name or "").lower()
    if any(value.startswith(name) for name in DATE_TYPES):
        return "date"
    if value in NUMBER_TYPES or value.startswith(("int", "float", "decimal")):
        return "number"
    if value in TEXT_TYPES or value.startswith("str"):
        return "text"
    return "any"


def _fits_kind(role: Role, type_name: str | None) -> bool:
    if role.kind == "any":
        return True
    kind = _kind_of(type_name)
    # Dates often arrive as text; a date role accepts a text column and the
    # template parses it.
    if role.kind == "date":
        return kind in {"date", "text", "any"}
    return kind == role.kind or kind == "any"


def _words(name: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", name.lower()) if part}


def _score(role: Role, column: str) -> int:
    lowered = column.lower()
    words = _words(column)
    best = 0
    for hint in role.hints:
        if lowered == hint:
            best = max(best, 3)
        elif hint in words:
            best = max(best, 2)
        elif len(hint) >= 4 and hint in lowered:
            # Only longer hints match inside a name: "on" is in "notes" and
            # "at" is in "status", and neither is a date.
            best = max(best, 1)
    return best


def suggest_mapping(
    template: Template, columns: Sequence[str], types: Mapping[str, str]
) -> tuple[dict[str, Any], list[str]]:
    """The best column for each role, and the required roles nothing fits."""
    mapping: dict[str, Any] = {}
    missing: list[str] = []
    taken: set[str] = set()
    for role in template.roles:
        candidates = [
            column
            for column in columns
            if column not in taken and _fits_kind(role, types.get(column))
        ]
        if role.multiple:
            chosen = [column for column in candidates if _score(role, column) > 0]
            if not chosen and role.kind != "any":
                chosen = candidates
            mapping[role.key] = chosen
            if role.required and not chosen:
                missing.append(role.key)
            continue
        ranked = sorted(candidates, key=lambda column: -_score(role, column))
        if ranked and _score(role, ranked[0]) > 0:
            mapping[role.key] = ranked[0]
            taken.add(ranked[0])
        elif role.required:
            missing.append(role.key)
    return mapping, missing


def _text_columns(columns: Sequence[str], types: Mapping[str, str]) -> list[str]:
    return [column for column in columns if _kind_of(types.get(column)) == "text"]


def _single(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) and value else None


def _many(mapping: Mapping[str, Any], key: str) -> list[str]:
    value = mapping.get(key)
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


# ---------------------------------------------------------------- templates


def _clean_contacts(mapping, columns, types) -> list[dict[str, Any]]:
    email = _single(mapping, "email")
    name = _single(mapping, "name")
    steps: list[dict[str, Any]] = []
    text = _text_columns(columns, types) or [column for column in (email, name) if column]
    if text:
        steps.append({"step_type": "trim_strings", "config": {"columns": text}})
    if email:
        steps.append(
            {
                "step_type": "derive_column",
                "config": {"target_column": email, "formula": f"=LOWER([{email}])", "overwrite": True},
            }
        )
    if name:
        steps.append(
            {
                "step_type": "derive_column",
                "config": {"target_column": name, "formula": f"=PROPER([{name}])", "overwrite": True},
            }
        )
    if email:
        steps.append(
            {"step_type": "drop_null_rows", "config": {"how": "any", "columns": [email]}}
        )
        steps.append(
            {"step_type": "remove_duplicates", "config": {"subset": [email], "keep": "first"}}
        )
    return steps


def _monthly_totals(mapping, columns, types) -> list[dict[str, Any]]:
    date = _single(mapping, "date")
    amount = _single(mapping, "amount")
    group = _single(mapping, "group")
    if not date or not amount:
        raise BadRequestError("Choose a date column and an amount column.")
    month = "month" if "month" not in columns else f"{date}_month"
    steps: list[dict[str, Any]] = []
    if _kind_of(types.get(date)) != "date":
        steps.append({"step_type": "parse_dates", "config": {"columns": [date]}})
    steps.append(
        {
            "step_type": "derive_column",
            "config": {"target_column": month, "formula": f'=FORMAT_DATE([{date}], "%Y-%m")'},
        }
    )
    group_by = [month, *([group] if group else [])]
    steps.append(
        {
            "step_type": "aggregate",
            "config": {
                "group_by": group_by,
                "aggregations": [
                    {"column": amount, "function": "sum", "alias": f"total_{amount}"},
                    # Counted on the date, which every row has once parsed;
                    # counting the amount would skip rows where it is empty.
                    {"column": date, "function": "count", "alias": "rows"},
                ],
            },
        }
    )
    steps.append({"step_type": "sort_rows", "config": {"columns": group_by}})
    return steps


def _tidy_and_dedupe(mapping, columns, types) -> list[dict[str, Any]]:
    keys = _many(mapping, "keys")
    text = _many(mapping, "text") or _text_columns(columns, types)
    steps: list[dict[str, Any]] = []
    if text:
        steps.append({"step_type": "trim_strings", "config": {"columns": text}})
    config: dict[str, Any] = {"keep": "first"}
    if keys:
        config["subset"] = keys
    steps.append({"step_type": "remove_duplicates", "config": config})
    return steps


TEMPLATES: tuple[Template, ...] = (
    Template(
        id="clean_contacts",
        name="Clean a contact list",
        description=(
            "Trim stray spaces, write emails in lower case and names in title case, "
            "drop rows with no email and keep one row per email."
        ),
        roles=(
            Role(
                key="email",
                label="Email column",
                description="Used to find duplicates and rows with no contact.",
                kind="text",
                hints=("email", "e_mail", "mail", "email_address"),
            ),
            Role(
                key="name",
                label="Name column",
                description="Written in title case. Leave empty to skip.",
                kind="text",
                hints=("name", "full_name", "customer_name", "contact"),
                required=False,
            ),
        ),
        build=_clean_contacts,
    ),
    Template(
        id="monthly_totals",
        name="Monthly totals",
        description="Add up an amount for each month, optionally split by a category such as region.",
        roles=(
            Role(
                key="date",
                label="Date column",
                description="Which date decides the month.",
                kind="date",
                hints=("date", "day", "created", "issued", "ordered", "order_date", "at", "on"),
            ),
            Role(
                key="amount",
                label="Amount column",
                description="The number to add up.",
                kind="number",
                hints=("amount", "total", "revenue", "sales", "value", "price", "cost"),
            ),
            Role(
                key="group",
                label="Split by (optional)",
                description="A category to total separately, such as region.",
                kind="text",
                hints=("region", "category", "country", "segment", "channel", "product", "status"),
                required=False,
            ),
        ),
        build=_monthly_totals,
    ),
    Template(
        id="tidy_and_dedupe",
        name="Remove duplicates and tidy text",
        description="Trim stray spaces from text, then keep one row for each key, or each identical row.",
        roles=(
            Role(
                key="keys",
                label="What makes a row unique",
                description="Rows with the same values here count as duplicates. Leave empty to compare whole rows.",
                hints=("id", "key", "code", "number", "email"),
                required=False,
                multiple=True,
            ),
            Role(
                key="text",
                label="Text columns to tidy",
                description="Leave empty to tidy every text column.",
                kind="text",
                required=False,
                multiple=True,
            ),
        ),
        build=_tidy_and_dedupe,
    ),
)

_BY_ID = {template.id: template for template in TEMPLATES}


def get_template(template_id: str) -> Template:
    template = _BY_ID.get(template_id)
    if template is None:
        raise NotFoundError(f"There is no recipe template called '{template_id}'.")
    return template


def build_steps(
    template_id: str,
    mapping: Mapping[str, Any],
    columns: Sequence[str],
    types: Mapping[str, str],
) -> list[dict[str, Any]]:
    """The template's steps for these columns, after checking the mapping."""
    template = get_template(template_id)
    known = set(columns)
    for role in template.roles:
        chosen = _many(mapping, role.key) if role.multiple else (
            [_single(mapping, role.key)] if _single(mapping, role.key) else []
        )
        unknown = [column for column in chosen if column not in known]
        if unknown:
            raise BadRequestError(
                f"{role.label}: {', '.join(unknown)} is not a column in this dataset."
            )
        if role.required and not chosen:
            raise BadRequestError(f"Choose the {role.label.lower()}.")
    return template.build(mapping, list(columns), dict(types))
