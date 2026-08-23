"""The tool reference, generated from the registry.

Every entry is built from the same :class:`ToolSpec` the engine runs, and every
example in it is asserted by ``test_tool_library.py``. A reference written by
hand beside a library of hundreds is a reference that is wrong within a month;
this one cannot be, because there is nothing to keep in step.
"""

from __future__ import annotations

from typing import Any

from service_transformations.tools import TOOLS, categories
from service_transformations.tools.spec import ToolSpec


def _example_table(spec: ToolSpec) -> list[str]:
    example = spec.example
    if not example.expect:
        return [f"_{example.note}_"] if example.note else []

    column = example.column or (list(example.rows[0]) if example.rows else [None])[0]
    heading = "columns" if example.output == "__columns__" else (example.output or column)
    lines = [
        f"| `{column}` | `{heading}` |",
        "|---|---|",
    ]
    for row, produced in zip(example.rows, example.expect):
        given = row.get(column) if column else None
        lines.append(f"| {_cell(given)} | {_cell(produced)} |")
    if example.note:
        lines.append("")
        lines.append(f"_{example.note}_")
    return lines


#: Control characters, shown as their escapes. A table cell holding a literal
#: newline or tab is broken markdown -- the row splits across lines -- and a
#: literal CR also makes the file fail a byte-for-byte comparison, because
#: reading it back normalises the line ending.
_ESCAPES = {
    "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t",
    "\x00": "\\0", "|": "\\|",
}


def _cell(value: Any) -> str:
    if value is None:
        return "_(empty)_"
    if value == "":
        return "_(blank)_"
    rendered = str(value)
    for character, escape in _ESCAPES.items():
        rendered = rendered.replace(character, escape)
    return f"`{rendered}`"


def _parameters(spec: ToolSpec) -> list[str]:
    if not spec.params:
        return []
    lines = ["| Setting | Type | Required | Default |", "|---|---|---|---|"]
    for param in spec.params:
        kind = param.kind.value
        if param.options:
            kind = " / ".join(f"`{option}`" for option in param.options)
        default = "—" if param.default in (None, "") else f"`{param.default}`"
        lines.append(
            f"| {param.label} | {kind} | {'yes' if param.required else 'no'} | {default} |"
        )
        if param.help:
            lines.append(f"| | {param.help} | | |")
    return lines


def as_markdown() -> str:
    """The whole catalogue, grouped by category."""
    total = len(TOOLS)
    lines = [
        "# Transformation tools",
        "",
        f"{total} tools across {len(categories())} categories. Every one compiles to the",
        "relational IR, so every one gets type inference, column lineage and",
        "pushdown without a second implementation.",
        "",
        "Generated from the tool registry. Every example below is executed by the",
        "test suite, so this file cannot describe behaviour the code does not have.",
        "",
        "## Contents",
        "",
    ]
    for category in categories():
        count = sum(1 for spec in TOOLS.values() if spec.category == category)
        anchor = category.lower().replace(" & ", "--").replace(" ", "-")
        lines.append(f"- [{category}](#{anchor}) ({count})")
    lines.append("")

    for category in categories():
        lines += ["", f"## {category}", ""]
        for spec in TOOLS.values():
            if spec.category != category:
                continue
            lines += [f"### {spec.title}", "", f"`{spec.name}`", "", spec.summary, ""]
            if spec.synonyms:
                lines += ["Also known as: " + ", ".join(f"_{s}_" for s in spec.synonyms), ""]
            if spec.accepts.value != "any":
                lines += [f"Offered on **{spec.accepts.value}** columns.", ""]
            parameters = _parameters(spec)
            if parameters:
                lines += parameters + [""]
            table = _example_table(spec)
            if table:
                lines += table + [""]
    return "\n".join(lines).rstrip() + "\n"


def as_json() -> list[dict[str, Any]]:
    """The catalogue as data, for the Studio's tool panel and palette."""
    return [
        {
            "name": spec.name,
            "title": spec.title,
            "category": spec.category,
            "summary": spec.summary,
            "synonyms": list(spec.synonyms),
            "accepts": spec.accepts.value,
            "column_scoped": spec.column_scoped,
            "params": [
                {
                    "key": param.key,
                    "label": param.label,
                    "kind": param.kind.value,
                    "required": param.required,
                    "default": param.default,
                    "options": list(param.options),
                    "help": param.help,
                    "placeholder": param.placeholder,
                    "minimum": param.minimum,
                    "maximum": param.maximum,
                }
                for param in spec.params
            ],
            "example": {
                "rows": [dict(row) for row in spec.example.rows],
                "params": dict(spec.example.params),
                "column": spec.example.column,
                "output": spec.example.output,
                "expect": list(spec.example.expect),
                "note": spec.example.note,
            },
        }
        for spec in TOOLS.values()
    ]
