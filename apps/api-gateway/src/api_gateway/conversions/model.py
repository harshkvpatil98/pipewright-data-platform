"""What converting another tool's work makes, and the report on it (E2, X3).

A converter reads a file and says, before anything is made, what it would
make: the datasets the work reads (which the project must have, matched by
name or chosen), the data the file carries itself (made into datasets),
recipes, checks and workflows, and a report of every part of the file and
what became of it. Making them is ``apply.py``'s, through each service's
ordinary create function.

Things refer to each other by key, never by id: a step that reads another
dataset holds ``{"$dataset": key}``, a workflow task ``{"$recipe": key}`` or
``{"$checks": [key, ...]}``. A recipe's key read as a dataset means the
dataset its runs write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from shared_python.types import PWType

Status = Literal["converted", "not converted", "nothing to do"]


class NotConverted(Exception):
    """A part of the file that has no exact conversion here, and why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Entry:
    """One part of the file and what became of it."""

    subject: str
    status: Status
    #: What it became, step by step: "Step 2 of “orders”: Transform with SQL".
    became: list[str] = field(default_factory=list)
    reason: str | None = None
    #: How it runs here, where that is worth knowing.
    notes: list[str] = field(default_factory=list)


@dataclass
class Section:
    """A unit of the file (a model, a job, a query) and its parts."""

    title: str
    entries: list[Entry] = field(default_factory=list)

    def converted(self, subject: str, became: list[str] | str, notes: list[str] | None = None) -> Entry:
        entry = Entry(subject, "converted", [became] if isinstance(became, str) else list(became), None,
                      list(notes or []))
        self.entries.append(entry)
        return entry

    def not_converted(self, subject: str, reason: str) -> Entry:
        entry = Entry(subject, "not converted", [], reason)
        self.entries.append(entry)
        return entry

    def nothing_to_do(self, subject: str, reason: str) -> Entry:
        entry = Entry(subject, "nothing to do", [], reason)
        self.entries.append(entry)
        return entry


@dataclass
class Needed:
    """A dataset the converted work reads, which the project must have."""

    key: str
    #: The name it is matched by among the project's datasets.
    name: str
    #: What the file calls it: "the dbt source shop.orders".
    what: str
    #: The columns the converted work reads of it, where they can be said.
    columns: list[str] = field(default_factory=list)
    #: Its columns' types, where the file declares them.
    types: dict[str, PWType] = field(default_factory=dict)


@dataclass
class Seed:
    """Data the file carries itself, made into a dataset."""

    key: str
    name: str
    what: str
    file_name: str
    data: bytes


@dataclass
class RecipePlan:
    key: str
    name: str
    description: str
    #: The key of what it reads: a needed dataset, a seed, or a recipe.
    reads: str
    steps: list[dict[str, Any]]
    parameters: list[dict[str, Any]] = field(default_factory=list)
    #: False when a part of it did not convert: it holds the steps up to that
    #: part, is made as a draft and is never run, and nothing reads it.
    complete: bool = True
    #: Its columns, as the steps leave them, where known.
    columns: dict[str, PWType] | None = None

    def reads_all(self) -> list[str]:
        """The keys of everything it reads: its dataset, and any its steps bring in."""
        found = [self.reads]

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if "$dataset" in value:
                    found.append(str(value["$dataset"]))
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(self.steps)
        return list(dict.fromkeys(found))


@dataclass
class CheckPlan:
    key: str
    name: str
    #: The key of the dataset it checks: a needed dataset, a seed, or a recipe's.
    reads: str
    rule_type: str
    config: dict[str, Any]
    severity: str = "error"
    description: str | None = None


@dataclass
class TaskPlan:
    node_key: str
    name: str
    node_type: str
    config: dict[str, Any]
    retries: int = 0
    retry_delay_seconds: int = 30
    continue_on_failure: bool = False


@dataclass
class LinkPlan:
    source: str
    target: str
    condition: str = "on_success"


@dataclass
class WorkflowPlan:
    key: str
    name: str
    description: str
    tasks: list[TaskPlan]
    links: list[LinkPlan]
    trigger_type: str = "manual"
    cron_expression: str | None = None
    timezone: str | None = None
    #: Values a run uses unless it is given others: {{ params.name }} in a task's settings.
    default_parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class Conversion:
    #: Which converter read it: "dbt", "airflow", "alteryx", ...
    format: str
    #: What the file is, in words: "the dbt project shop".
    title: str
    needs: list[Needed] = field(default_factory=list)
    seeds: list[Seed] = field(default_factory=list)
    recipes: list[RecipePlan] = field(default_factory=list)
    checks: list[CheckPlan] = field(default_factory=list)
    workflows: list[WorkflowPlan] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    #: About the conversion as a whole.
    notes: list[str] = field(default_factory=list)

    def need(self, key: str, name: str, what: str, *, columns: list[str] | None = None,
             types: dict[str, PWType] | None = None) -> Needed:
        for found in self.needs:
            if found.key == key:
                for column in columns or []:
                    if column not in found.columns:
                        found.columns.append(column)
                return found
        made = Needed(key, name, what, list(columns or []), dict(types or {}))
        self.needs.append(made)
        return made

    def section(self, title: str) -> Section:
        made = Section(title)
        self.sections.append(made)
        return made

    def recipe(self, key: str) -> RecipePlan | None:
        return next((recipe for recipe in self.recipes if recipe.key == key), None)


def node_key(wanted: str, taken: list[TaskPlan]) -> str:
    """A workflow task's key, from its name: lower case, letters, digits and _."""
    import re

    base = re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]", "_", wanted.lower())).strip("_")[:56] or "task"
    if not base[0].isalpha():
        base = f"t_{base}"[:56]
    key, number = base, 2
    while any(task.node_key == key for task in taken):
        key, number = f"{base}_{number}", number + 1
    return key


def run_in_order(conversion: Conversion, *, key: str, name: str, description: str,
                 recipes: list[RecipePlan] | None = None) -> tuple[WorkflowPlan, dict[str, str]] | None:
    """A workflow that runs recipes after the recipes they read: a recipe made for a branch (a join's other side,
    a union's second input) before the one that reads it, so a run never reads a branch's earlier result.
    Returns it and each recipe's task, or None when there is nothing to run."""
    chosen = [recipe for recipe in (recipes if recipes is not None else conversion.recipes) if recipe.complete]
    if not chosen:
        return None
    tasks: list[TaskPlan] = []
    task_of: dict[str, str] = {}
    for recipe in chosen:
        node = node_key(recipe.name, tasks)
        tasks.append(TaskPlan(node_key=node, name=f"Run {recipe.name}"[:160], node_type="transformation",
                              config={"pipeline_id": {"$recipe": recipe.key}}))
        task_of[recipe.key] = node
    links = [LinkPlan(task_of[read], task_of[recipe.key]) for recipe in chosen for read in recipe.reads_all()
             if read in task_of and read != recipe.key]
    return WorkflowPlan(key=key, name=name[:160], description=description, tasks=tasks, links=links), task_of
