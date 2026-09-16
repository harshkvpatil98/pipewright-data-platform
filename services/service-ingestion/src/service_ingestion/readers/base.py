"""What every reader returns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from service_ingestion.sniff.columns import ColumnProfile
from service_ingestion.sniff.evidence import Finding


@dataclass
class ReadResult:
    """A frame, and everything learned while producing it."""

    frame: pd.DataFrame
    #: The options that would reproduce this read exactly. They become the
    #: spec, which is what makes next month's file read the same way.
    options: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    #: Set only when the format states its own types. An inferred profile must
    #: not overwrite a declared one.
    declared_columns: list[ColumnProfile] = field(default_factory=list)
    #: Other tables in the same file: Excel sheets, the tables in a SQL dump.
    tables: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Column names that are usable, distinct and stable.

    Unnamed columns become positional names rather than pandas' `Unnamed: 3`,
    which looks like data and breaks the moment a column is inserted upstream.
    """
    names: list[str] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(frame.columns):
        name = str(raw).strip()
        if not name or name.lower().startswith("unnamed:"):
            name = f"column_{index + 1}"
        key = name.lower()
        if key in seen:
            seen[key] += 1
            name = f"{name}_{seen[key]}"
        else:
            seen[key] = 1
        names.append(name)
    out = frame.copy()
    out.columns = names
    return out


def declared_profile(name: str, pw_type: Any, reason: str) -> ColumnProfile:
    """A column whose type the file stated rather than one we guessed."""
    from service_ingestion.sniff.evidence import certain

    return ColumnProfile(
        name=name,
        pw_type=pw_type,
        finding=certain("column_type", str(pw_type), reason),
    )
