"""Impact analysis: what breaks if this column changes.

The question a person actually asks before dropping a column is "will anything
notice?" -- and the honest answer has three grades, not two:

``breaks``
    Something names this column explicitly. It will raise on the next run.
``changes``
    Something consumes every column without naming this one -- a dedupe with no
    subset, a union. The run still succeeds and quietly produces different
    numbers, which is the worse outcome of the two.
``informational``
    A downstream artifact exists but the column does not reach it.

Everything here is pure: rows come in as plain dicts, findings go out. The
database work lives in :mod:`service_lineage.service`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from service_transformations.expressions import referenced_columns

from service_lineage.columns import PipelineLineage, SchemaResolver, build_pipeline_lineage

# Steps that consume the whole frame when their column list is omitted.
_WHOLE_FRAME_WHEN_EMPTY = {
    "drop_null_rows": "columns",
    "remove_duplicates": "subset",
}


@dataclass(frozen=True)
class ImpactFinding:
    kind: str
    id: str
    name: str
    severity: str
    detail: str
    columns: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "severity": self.severity,
            "detail": self.detail,
            "columns": list(self.columns),
        }


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _quote_all(names: Sequence[str]) -> str:
    return ", ".join(f"'{name}'" for name in names)


# --------------------------------------------------------------------------
# Pipelines built directly on the dataset
# --------------------------------------------------------------------------


def pipeline_impact(
    *,
    pipeline_id: str,
    pipeline_name: str,
    base_columns: Sequence[str],
    steps: Sequence[dict[str, Any]],
    targeted: Sequence[str],
    resolve_schema: SchemaResolver | None = None,
) -> list[ImpactFinding]:
    """Findings for a pipeline whose *base* dataset owns the targeted columns."""

    lineage = build_pipeline_lineage(
        base_columns=base_columns, steps=steps, resolve_schema=resolve_schema
    )
    findings: list[ImpactFinding] = []

    for column in targeted:
        naming_steps = _steps_naming_column(lineage, column)
        outputs = lineage.downstream_of(column)
        reads = lineage.reads_of(column)

        if naming_steps:
            first = naming_steps[0]
            detail = (
                f"Step {first[0] + 1} ({first[1].replace('_', ' ')}) names '{column}' directly, "
                f"so the pipeline fails on its next run."
            )
            if outputs:
                detail += f" It also feeds {_plural(len(outputs), 'output column')}: {_quote_all(outputs)}."
            findings.append(
                ImpactFinding(
                    kind="pipeline",
                    id=pipeline_id,
                    name=pipeline_name,
                    severity="breaks",
                    detail=detail,
                    columns=(column,),
                )
            )
            continue

        implicit = _implicit_consumers(lineage, column)
        if implicit:
            step_index, step_type = implicit[0]
            findings.append(
                ImpactFinding(
                    kind="pipeline",
                    id=pipeline_id,
                    name=pipeline_name,
                    severity="changes",
                    detail=(
                        f"Step {step_index + 1} ({step_type.replace('_', ' ')}) consumes every column, "
                        f"so removing '{column}' changes which rows survive without raising an error."
                    ),
                    columns=(column,),
                )
            )
            continue

        if outputs or reads:
            # Reaching the output under its own name is a different sentence
            # from feeding a computed column, and people act on them differently.
            carried = column in outputs
            others = [name for name in outputs if name != column]
            if carried and not others:
                detail = f"'{column}' passes straight through, so the pipeline's output loses it."
            elif carried:
                detail = (
                    f"'{column}' passes straight through and also feeds "
                    f"{_plural(len(others), 'computed column')}: {_quote_all(others)}."
                )
            elif others:
                detail = (
                    f"'{column}' feeds {_plural(len(others), 'output column')} "
                    f"({_quote_all(others)}) that would lose their values."
                )
            else:
                detail = f"'{column}' is read by this pipeline without appearing in its output."

            findings.append(
                ImpactFinding(
                    kind="pipeline",
                    id=pipeline_id,
                    name=pipeline_name,
                    severity="changes",
                    detail=detail,
                    columns=(column,),
                )
            )

    return findings


def _walk_names(lineage: PipelineLineage, column: str) -> Iterator[tuple[Any, set[str]]]:
    """Yield each step alongside the names ``column`` goes by entering it.

    A rename means later steps never see the original name, so a search that
    ignored renames would report breakage that cannot happen.
    """
    current = {column}
    for step in lineage.steps:
        if not current:
            return
        yield step, current
        renamed = {
            edge.to_column
            for edge in step.edges
            if edge.kind == "rename" and edge.from_column in current
        }
        survivors = {name for name in current if name in step.output_columns}
        current = survivors | renamed


def _steps_naming_column(lineage: PipelineLineage, column: str) -> list[tuple[int, str]]:
    """Steps that would raise because their config spells this column out."""
    return [
        (step.step_index, step.step_type)
        for step, names in _walk_names(lineage, column)
        if names & set(step.named_columns)
    ]


def _implicit_consumers(lineage: PipelineLineage, column: str) -> list[tuple[int, str]]:
    """Steps that consume every column, where losing one changes results quietly."""
    hits: list[tuple[int, str]] = []
    for step, names in _walk_names(lineage, column):
        if step.step_type not in _WHOLE_FRAME_WHEN_EMPTY or step.named_columns:
            continue
        if names & {read.column for read in step.reads}:
            hits.append((step.step_index, step.step_type))
    return hits


# --------------------------------------------------------------------------
# Pipelines that read the dataset as a second input
# --------------------------------------------------------------------------


def secondary_input_impact(
    *,
    pipeline_id: str,
    pipeline_name: str,
    steps: Sequence[dict[str, Any]],
    dataset_id: str,
    targeted: Sequence[str],
) -> list[ImpactFinding]:
    """Findings for a pipeline that joins or unions the targeted dataset in."""

    findings: list[ImpactFinding] = []
    wanted = set(targeted)

    for index, raw in enumerate(steps):
        raw = raw if isinstance(raw, dict) else {}
        step_type = raw.get("step_type")
        config = raw.get("config") if isinstance(raw.get("config"), dict) else {}

        if step_type == "join_datasets" and config.get("right_dataset_id") == dataset_id:
            keys = [name for name in _string_list(config.get("right_on")) if name in wanted]
            selected = [name for name in _string_list(config.get("select_right_columns")) if name in wanted]
            named = sorted({*keys, *selected})
            if named:
                findings.append(
                    ImpactFinding(
                        kind="pipeline",
                        id=pipeline_id,
                        name=pipeline_name,
                        severity="breaks",
                        detail=(
                            f"Step {index + 1} joins this dataset on {_quote_all(named)}, "
                            "which the join names explicitly."
                        ),
                        columns=tuple(named),
                    )
                )
            elif config.get("select_right_columns") is None:
                findings.append(
                    ImpactFinding(
                        kind="pipeline",
                        id=pipeline_id,
                        name=pipeline_name,
                        severity="changes",
                        detail=(
                            f"Step {index + 1} joins this dataset and takes every column, "
                            "so the joined output loses these columns."
                        ),
                        columns=tuple(sorted(wanted)),
                    )
                )

        elif step_type == "union_datasets" and config.get("other_dataset_id") == dataset_id:
            strategy = str(config.get("column_strategy", "union")).lower()
            severity = "breaks" if strategy == "strict" else "changes"
            detail = (
                f"Step {index + 1} unions this dataset with column_strategy '{strategy}', "
                + (
                    "which requires the column sets to match exactly."
                    if strategy == "strict"
                    else "so the combined output changes shape."
                )
            )
            findings.append(
                ImpactFinding(
                    kind="pipeline",
                    id=pipeline_id,
                    name=pipeline_name,
                    severity=severity,
                    detail=detail,
                    columns=tuple(sorted(wanted)),
                )
            )

    return findings


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


# --------------------------------------------------------------------------
# Quality rules
# --------------------------------------------------------------------------


def rule_referenced_columns(config: Any) -> set[str]:
    """Columns a quality rule config names, whatever shape the rule takes."""
    if not isinstance(config, dict):
        return set()

    names: set[str] = set()
    single = config.get("column")
    if isinstance(single, str) and single.strip():
        names.add(single.strip())
    names.update(_string_list(config.get("columns")))

    expression = config.get("expression")
    if isinstance(expression, str):
        names.update(referenced_columns(expression))

    return names


def quality_rule_impact(
    *,
    rule_id: str,
    rule_name: str,
    rule_type: str,
    severity: str,
    config: Any,
    targeted: Sequence[str],
) -> ImpactFinding | None:
    referenced = rule_referenced_columns(config)
    hit = sorted(referenced & set(targeted))
    if not hit:
        return None

    consequence = (
        "the run's quality gate fails" if severity == "error" else "the rule reports an error instead of a result"
    )
    return ImpactFinding(
        kind="quality_rule",
        id=rule_id,
        name=rule_name,
        severity="breaks",
        detail=(
            f"The {rule_type.replace('_', ' ')} rule checks {_quote_all(hit)}, "
            f"so {consequence}."
        ),
        columns=tuple(hit),
    )


# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------


def workflow_impact(
    *,
    workflow_id: str,
    workflow_name: str,
    node_names: Sequence[str],
    targeted: Sequence[str],
    reason: str,
) -> ImpactFinding:
    node_text = ", ".join(node_names[:3]) + ("…" if len(node_names) > 3 else "")
    return ImpactFinding(
        kind="workflow",
        id=workflow_id,
        name=workflow_name,
        severity="changes",
        detail=f"{reason} ({node_text}).",
        columns=tuple(sorted(set(targeted))),
    )


def summarise(findings: Sequence[ImpactFinding], columns: Sequence[str]) -> str:
    """One sentence a person can act on without reading the table."""
    breaks = [finding for finding in findings if finding.severity == "breaks"]
    changes = [finding for finding in findings if finding.severity == "changes"]
    subject = _quote_all(columns) if len(columns) <= 3 else _plural(len(columns), "column")

    if not findings:
        return f"Nothing downstream reads {subject}. It is safe to drop."
    if breaks and changes:
        return (
            f"Dropping {subject} breaks {_plural(len(breaks), 'thing')} outright and "
            f"silently changes {_plural(len(changes), 'other')}."
        )
    if breaks:
        return f"Dropping {subject} breaks {_plural(len(breaks), 'downstream artifact')} on its next run."
    return (
        f"Dropping {subject} raises no errors, but {_plural(len(changes), 'downstream artifact')} "
        "quietly produces different results."
    )
