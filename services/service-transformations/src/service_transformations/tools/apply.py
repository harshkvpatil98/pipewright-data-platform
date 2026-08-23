"""Running a tool step.

The library's execution path goes through the IR rather than pandas directly:
a tool builds a node over a `Scan` of the working frame, and the pandas backend
runs it. That is what makes "every tool compiles to IR" true rather than
aspirational -- there is no second implementation for it to drift from.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types.inference import infer_pw_type

from service_transformations.ir import pandas_backend
from service_transformations.ir.nodes import IRError, Node, Scan
from service_transformations.tools import build as build_tool, get

#: The name the working frame is bound to while a tool runs.
SOURCE = "__frame__"


def scan_of(frame: pd.DataFrame) -> Scan:
    """A `Scan` describing the frame, typed from its contents."""
    return Scan(
        source=SOURCE,
        columns=tuple((str(name), infer_pw_type(frame[name])) for name in frame.columns),
    )


def build(frame: pd.DataFrame, config: dict[str, Any]) -> Node:
    return build_tool(scan_of(frame), config)


def apply_tool(
    frame: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, list[str]]:
    """Apply one tool to a frame, reporting anything the person should know."""
    name = config.get("tool")
    try:
        node = build(frame, config)
    except IRError as exc:
        # An IR error at this point is a configuration problem, not a bug: the
        # tool was pointed at a column whose type it cannot work with.
        raise BadRequestError(str(exc)) from exc

    try:
        result = pandas_backend.execute(node, {SOURCE: frame})
    except IRError as exc:
        raise BadRequestError(f"{get(str(name)).title}: {exc}") from exc
    except re.error as exc:
        # A pattern that will not compile is something the person typed, not a
        # fault. Without this it is a 500 with a stack trace and no clue which
        # character was wrong.
        raise BadRequestError(
            f"{get(str(name)).title}: that pattern will not compile -- {exc}."
        ) from exc

    return result, _warnings(frame, result, config)


def _warnings(
    before: pd.DataFrame, after: pd.DataFrame, config: dict[str, Any]
) -> list[str]:
    """Report the silent failure mode: a tool that turned values into nulls.

    A tool cannot raise on a bad row without failing a run for one cell, so it
    produces null. That is right, and invisible unless somebody says so.
    """
    spec = get(str(config.get("tool")))
    if not spec.column_scoped:
        return []
    source = config.get("column")
    target = config.get("into") or source
    if not source or source not in before.columns or target not in after.columns:
        return []

    had_value = before[source].notna()
    eligible = int(had_value.sum())
    if not eligible:
        return []
    lost = int((had_value & after[target].isna().reindex(had_value.index, fill_value=False)).sum())
    if not lost:
        return []
    return [
        f"{spec.title} could not read {lost:,} of {eligible:,} value(s) in "
        f"{source!r}; those rows are now empty."
    ]
