"""Row and column policies, applied wherever rows reach a person (A6, W1).

A policy only protects the read paths that ask. Download asked first; this
module is what every other read path asks: the dataset's preview, profile and
versions, charts and dashboards (public links included), the Studio preview,
the assistant, comparisons and SQL over a version. Each takes a `Reader`,
which says whose eyes the rows are for, and gets back only what that reader's
role may see.

It imports nothing from the services that call it, so any of them can import
it without a cycle.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_enterprise import security
from service_enterprise.models import SecurityPolicy
from service_projects.contracts import project_role


@dataclass(frozen=True)
class Reader:
    """Whose eyes rows are for. Policies apply by project role."""

    role: str

    @classmethod
    def for_user(cls, db: Session, project_id: uuid.UUID, user: Any) -> Reader:
        """A signed-in person, by their role on the project. No role reads as a viewer."""
        return cls(role=project_role(db, project_id, user.id) or "viewer")


#: Someone opening a public dashboard link: as restricted as a viewer.
PUBLIC = Reader(role="viewer")


@dataclass(frozen=True)
class PolicyView:
    """The policies that apply to one reader on one dataset, and how to apply them."""

    role: str
    policies: tuple[security.Policy, ...]

    @property
    def restricted(self) -> bool:
        return bool(self.policies)

    @property
    def filters_rows(self) -> bool:
        return any(policy.row_rules for policy in self.policies)

    def column_action(self, column: str) -> str:
        return security.effective_column_action(self.policies, column)

    def visible_columns(self, columns: list[str]) -> list[str]:
        """Column names this reader may know exist (denied columns are left out)."""
        return [column for column in columns if self.column_action(str(column)) != "deny"]

    def frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        if not self.restricted:
            return frame
        narrowed, _applied = security.apply_policies(frame, list(self.policies), role=self.role)
        return narrowed

    def preview(self, preview: dict[str, Any] | None) -> dict[str, Any] | None:
        """A stored preview ({"columns": [...], "rows": [{...}]}) narrowed the same way."""
        if not preview or not self.restricted:
            return preview
        columns = [str(column) for column in preview.get("columns", [])]
        rows = list(preview.get("rows", []))
        frame = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)
        narrowed = self.frame(frame)
        kept = [column for column in columns if column in narrowed.columns]
        records = narrowed[kept].astype(object).where(pd.notna(narrowed[kept]), None).to_dict(orient="records")
        return {**preview, "columns": kept, "rows": records}

    def profile(self, profile: dict[str, Any] | None) -> dict[str, Any] | None:
        """A stored profile with nothing a policy hides.

        The profile was computed over every row, so when a policy filters
        rows its figures would describe rows this reader cannot see: only each
        column's name and type are kept. Otherwise denied columns are dropped
        and masked columns lose their values (samples, minimum, maximum,
        averages), keeping the counts.
        """
        if not profile or not self.restricted:
            return profile
        columns = []
        for entry in profile.get("columns", []) or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", ""))
            action = self.column_action(name)
            if action == "deny":
                continue
            if self.filters_rows:
                columns.append({"name": name, "inferred_type": entry.get("inferred_type")})
            elif action != "allow":
                columns.append({
                    **entry,
                    "sample_values": [],
                    "min_value": None,
                    "max_value": None,
                    "mean_value": None,
                    "std_value": None,
                })
            else:
                columns.append(entry)
        narrowed: dict[str, Any] = {"columns": columns, "restricted_by_policy": True}
        if not self.filters_rows:
            for key, value in profile.items():
                if key != "columns":
                    narrowed[key] = self._scrub(value)
        return narrowed

    def schema(self, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        """A stored schema without the columns this reader may not know exist."""
        if not schema or not self.restricted:
            return schema
        narrowed = dict(schema)
        if isinstance(schema.get("columns"), list):
            narrowed["columns"] = [
                entry
                for entry in schema["columns"]
                if not (isinstance(entry, dict) and self.column_action(str(entry.get("name", ""))) == "deny")
            ]
        return {key: (value if key == "columns" else self._scrub(value)) for key, value in narrowed.items()}

    def _scrub(self, value: Any) -> Any:
        """Lists of column names lose the denied ones, however deep they sit."""
        if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            return self.visible_columns(value)
        if isinstance(value, dict):
            return {key: self._scrub(item) for key, item in value.items()}
        return value


def view_for(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, reader: Reader) -> PolicyView:
    """The enabled policies on this dataset that apply to this reader's role."""
    rows = db.scalars(
        select(SecurityPolicy).where(
            SecurityPolicy.project_id == project_id,
            SecurityPolicy.dataset_id == dataset_id,
            SecurityPolicy.enabled.is_(True),
            SecurityPolicy.role == reader.role,
        )
    ).all()
    policies = tuple(
        security.Policy(
            name=row.name,
            role=row.role,
            row_rules=[security.RowRule(**rule) for rule in (row.row_rules_json or [])],
            column_rules=[security.ColumnRule(**rule) for rule in (row.column_rules_json or [])],
            enabled=row.enabled,
        )
        for row in rows
    )
    return PolicyView(role=reader.role, policies=policies)


def narrow_frame(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, reader: Reader, frame: pd.DataFrame
) -> pd.DataFrame:
    """Shorthand for the commonest call: a frame, narrowed for a reader."""
    return view_for(db, project_id, dataset_id, reader).frame(frame)
