"""Lineage and impact analysis over a project's real datasets and pipelines."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.contracts import ensure_owned_project
from service_quality.models import DataQualityRule
from service_sources.models import Source
from service_transformations.models import TransformationPipeline
from service_workflows.models import Workflow, WorkflowNode
from shared_python.errors import BadRequestError, NotFoundError

from service_lineage import graph as graph_module
from service_lineage.columns import PipelineLineage, build_pipeline_lineage
from service_lineage.impact import (
    ImpactFinding,
    pipeline_impact,
    quality_rule_impact,
    secondary_input_impact,
    summarise,
    workflow_impact,
)
from service_lineage.schemas import (
    ColumnEdgeRead,
    ColumnOriginRead,
    ColumnReadRead,
    ColumnSummaryRead,
    ColumnTraceRead,
    DatasetLineageResponse,
    ImpactFindingRead,
    ImpactRequest,
    ImpactResponse,
    LineageEdgeRead,
    LineageNodeRead,
    StepLineageRead,
)

MAX_TRACED_COLUMNS = 300


def _dataset_columns(dataset: Dataset) -> list[str]:
    """A dataset's column names, from whichever snapshot is populated."""
    for candidate in (dataset.schema_json, dataset.schema_snapshot):
        if not isinstance(candidate, dict):
            continue
        ordered = candidate.get("ordered_columns")
        if isinstance(ordered, list) and ordered:
            return [str(name) for name in ordered]
        columns = candidate.get("columns")
        if isinstance(columns, list) and columns:
            names = [
                str(entry.get("name"))
                for entry in columns
                if isinstance(entry, dict) and entry.get("name")
            ]
            if names:
                return names
    preview = dataset.preview_json
    if isinstance(preview, dict) and isinstance(preview.get("columns"), list):
        return [str(name) for name in preview["columns"]]
    return []


def _get_dataset(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.project_id == project_id)
    )
    if dataset is None:
        raise NotFoundError("Dataset not found.")
    return dataset


def _project_datasets(db: Session, project_id: uuid.UUID) -> dict[str, Dataset]:
    rows = db.scalars(select(Dataset).where(Dataset.project_id == project_id)).all()
    return {str(dataset.id): dataset for dataset in rows}


def _project_pipelines(db: Session, project_id: uuid.UUID) -> list[TransformationPipeline]:
    return list(
        db.scalars(
            select(TransformationPipeline).where(TransformationPipeline.project_id == project_id)
        ).all()
    )


def _source_names(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = db.scalars(select(Source).where(Source.project_id == project_id)).all()
    return {source.id: source.name for source in rows}


def _schema_resolver(datasets: dict[str, Dataset]):
    def resolve(dataset_id: str) -> list[str] | None:
        dataset = datasets.get(dataset_id)
        if dataset is None:
            return None
        columns = _dataset_columns(dataset)
        return columns or None

    return resolve


def _producing_pipeline(
    dataset: Dataset, pipelines: list[TransformationPipeline]
) -> TransformationPipeline | None:
    """The pipeline that produced a derived dataset, if it is still around."""
    if dataset.created_from_pipeline_id is None:
        return None
    for pipeline in pipelines:
        if pipeline.id == dataset.created_from_pipeline_id:
            return pipeline
    return None


def _lineage_for_dataset(
    db: Session,
    dataset: Dataset,
    datasets: dict[str, Dataset],
    pipelines: list[TransformationPipeline],
) -> tuple[PipelineLineage | None, Dataset | None]:
    """Column lineage for a derived dataset, plus the dataset it was built from."""
    pipeline = _producing_pipeline(dataset, pipelines)
    if pipeline is None:
        return None, None

    base = datasets.get(str(pipeline.base_dataset_id))
    if base is None:
        base = db.get(Dataset, pipeline.base_dataset_id)
    if base is None:
        return None, None

    lineage = build_pipeline_lineage(
        base_columns=_dataset_columns(base),
        steps=pipeline.steps_json or [],
        resolve_schema=_schema_resolver(datasets),
    )
    return lineage, base


def _origin_reads(
    origins: list[Any], datasets: dict[str, Dataset], base: Dataset | None
) -> list[ColumnOriginRead]:
    reads: list[ColumnOriginRead] = []
    for origin in origins:
        if origin.dataset_id is None:
            name = base.name if base is not None else None
            dataset_id = str(base.id) if base is not None else None
        else:
            other = datasets.get(origin.dataset_id)
            name = other.name if other is not None else None
            dataset_id = origin.dataset_id
        reads.append(
            ColumnOriginRead(
                column=origin.column,
                dataset_id=dataset_id,
                dataset_name=name,
                created_at_step=origin.created_at_step,
            )
        )
    return reads


def _trace_sentence(column: str, origins: list[ColumnOriginRead], derived: bool) -> str:
    if not origins:
        return f"'{column}' has no traceable source; it is created inside the pipeline."
    parts = [
        f"'{origin.column}'" + (f" in {origin.dataset_name}" if origin.dataset_name else "")
        for origin in origins
    ]
    joined = ", ".join(parts[:-1]) + (" and " + parts[-1] if len(parts) > 1 else parts[0])
    if not derived:
        return f"'{column}' is {joined}, carried through unchanged."
    return f"'{column}' is computed from {joined}."


def get_dataset_lineage(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    current_user: UserRead,
    *,
    max_depth: int = graph_module.DEFAULT_MAX_DEPTH,
) -> DatasetLineageResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)

    datasets = _project_datasets(db, project_id)
    pipelines = _project_pipelines(db, project_id)
    sources = _source_names(db, project_id)

    graph_datasets = {
        key: graph_module.DatasetNode(
            id=key,
            name=record.name,
            is_derived=bool(record.is_derived),
            source_name=sources.get(record.source_id) if record.source_id else None,
            row_count=record.row_count,
        )
        for key, record in datasets.items()
    }
    outputs_by_pipeline: dict[uuid.UUID, list[str]] = {}
    for record in datasets.values():
        if record.created_from_pipeline_id is not None:
            outputs_by_pipeline.setdefault(record.created_from_pipeline_id, []).append(str(record.id))

    graph_pipelines = [
        graph_module.PipelineNode(
            id=str(pipeline.id),
            name=pipeline.name,
            base_dataset_id=str(pipeline.base_dataset_id),
            secondary_inputs=graph_module.secondary_input_ids(pipeline.steps_json),
            output_dataset_ids=tuple(outputs_by_pipeline.get(pipeline.id, ())),
        )
        for pipeline in pipelines
    ]

    graph = graph_module.build_graph(
        focus_dataset_id=str(dataset_id),
        datasets=graph_datasets,
        pipelines=graph_pipelines,
        max_depth=max_depth,
    )

    lineage, base = _lineage_for_dataset(db, dataset, datasets, pipelines)
    column_summaries: list[ColumnSummaryRead] = []
    step_reads: list[StepLineageRead] = []
    notes: list[str] = []

    if lineage is None:
        notes.append(
            "This dataset was loaded rather than computed, so its columns are sources rather than derivations."
        )
        for column in _dataset_columns(dataset)[:MAX_TRACED_COLUMNS]:
            column_summaries.append(
                ColumnSummaryRead(
                    column=column,
                    origins=[
                        ColumnOriginRead(
                            column=column,
                            dataset_id=str(dataset.id),
                            dataset_name=dataset.name,
                            created_at_step=None,
                        )
                    ],
                    derived=False,
                )
            )
    else:
        notes.extend(lineage.notes)
        for column in lineage.output_columns[:MAX_TRACED_COLUMNS]:
            trace = lineage.trace(column)
            origins = _origin_reads(trace.origins, datasets, base)
            derived = not (
                len(origins) == 1 and origins[0].column == column and origins[0].created_at_step is None
            )
            column_summaries.append(
                ColumnSummaryRead(column=column, origins=origins, derived=derived)
            )
        step_reads = [
            StepLineageRead(
                step_index=step.step_index,
                step_type=step.step_type,
                step_name=step.step_name,
                input_columns=step.input_columns,
                output_columns=step.output_columns,
                added_columns=step.added_columns,
                removed_columns=step.removed_columns,
                edges=[ColumnEdgeRead(**edge.to_dict()) for edge in step.edges],
                reads=[ColumnReadRead(**read.to_dict()) for read in step.reads],
                notes=step.notes,
                dynamic=step.dynamic,
            )
            for step in lineage.steps
        ]

    if graph.truncated:
        notes.append("The graph was trimmed at the depth limit; focus a further node to keep walking.")

    return DatasetLineageResponse(
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        nodes=[LineageNodeRead(**node.to_dict()) for node in graph.nodes],
        edges=[LineageEdgeRead(**edge.to_dict()) for edge in graph.edges],
        columns=column_summaries,
        steps=step_reads,
        notes=notes,
        partial=bool(lineage.dynamic) if lineage is not None else False,
    )


def trace_dataset_column(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    column: str,
    current_user: UserRead,
) -> ColumnTraceRead:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)
    datasets = _project_datasets(db, project_id)
    pipelines = _project_pipelines(db, project_id)

    lineage, base = _lineage_for_dataset(db, dataset, datasets, pipelines)
    if lineage is None:
        if column not in _dataset_columns(dataset):
            raise NotFoundError(f"Column '{column}' is not in this dataset.")
        origins = [
            ColumnOriginRead(
                column=column,
                dataset_id=str(dataset.id),
                dataset_name=dataset.name,
                created_at_step=None,
            )
        ]
        return ColumnTraceRead(
            column=column,
            origins=origins,
            edges=[],
            unresolved=False,
            summary=_trace_sentence(column, origins, derived=False),
        )

    if column not in lineage.output_columns:
        raise NotFoundError(f"Column '{column}' is not in this dataset's output.")

    trace = lineage.trace(column)
    origins = _origin_reads(trace.origins, datasets, base)
    derived = bool(trace.edges)
    return ColumnTraceRead(
        column=column,
        origins=origins,
        edges=[ColumnEdgeRead(**edge.to_dict()) for edge in trace.edges],
        unresolved=trace.unresolved,
        summary=_trace_sentence(column, origins, derived),
    )


def analyse_impact(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: ImpactRequest,
    current_user: UserRead,
) -> ImpactResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)

    available = _dataset_columns(dataset)
    targeted = [column.strip() for column in payload.columns if column.strip()]
    if not targeted:
        raise BadRequestError("Name at least one column to analyse.")
    if available:
        unknown = [column for column in targeted if column not in available]
        if unknown:
            raise BadRequestError(
                f"This dataset has no column(s) named: {', '.join(sorted(unknown))}."
            )

    datasets = _project_datasets(db, project_id)
    pipelines = _project_pipelines(db, project_id)
    resolver = _schema_resolver(datasets)
    dataset_key = str(dataset_id)
    findings: list[ImpactFinding] = []

    for pipeline in pipelines:
        steps = pipeline.steps_json or []
        if pipeline.base_dataset_id == dataset_id:
            findings.extend(
                pipeline_impact(
                    pipeline_id=str(pipeline.id),
                    pipeline_name=pipeline.name,
                    base_columns=available,
                    steps=steps,
                    targeted=targeted,
                    resolve_schema=resolver,
                )
            )
        findings.extend(
            secondary_input_impact(
                pipeline_id=str(pipeline.id),
                pipeline_name=pipeline.name,
                steps=steps,
                dataset_id=dataset_key,
                targeted=targeted,
            )
        )

    rules = db.scalars(
        select(DataQualityRule).where(
            DataQualityRule.project_id == project_id,
            DataQualityRule.dataset_id == dataset_id,
        )
    ).all()
    for rule in rules:
        finding = quality_rule_impact(
            rule_id=str(rule.id),
            rule_name=rule.name,
            rule_type=rule.rule_type,
            severity=rule.severity,
            config=rule.config_json,
            targeted=targeted,
        )
        if finding is not None:
            findings.append(finding)

    findings.extend(_workflow_findings(db, project_id, dataset_key, targeted))

    ordered = sorted(
        findings,
        key=lambda finding: ({"breaks": 0, "changes": 1, "informational": 2}[finding.severity], finding.name),
    )
    return ImpactResponse(
        dataset_id=dataset_id,
        columns=targeted,
        findings=[ImpactFindingRead(**finding.to_dict()) for finding in ordered],
        breaks_count=sum(1 for finding in ordered if finding.severity == "breaks"),
        changes_count=sum(1 for finding in ordered if finding.severity == "changes"),
        summary=summarise(ordered, targeted),
    )


def _workflow_findings(
    db: Session, project_id: uuid.UUID, dataset_key: str, targeted: list[str]
) -> list[ImpactFinding]:
    """Workflows whose nodes name this dataset, grouped one finding per workflow."""
    nodes = db.scalars(
        select(WorkflowNode).where(WorkflowNode.project_id == project_id)
    ).all()

    by_workflow: dict[uuid.UUID, list[str]] = {}
    for node in nodes:
        config = node.config_json if isinstance(node.config_json, dict) else {}
        if dataset_key in {str(value) for value in config.values() if isinstance(value, (str, uuid.UUID))}:
            by_workflow.setdefault(node.workflow_id, []).append(node.name)

    if not by_workflow:
        return []

    workflows = db.scalars(
        select(Workflow).where(Workflow.id.in_(list(by_workflow.keys())))
    ).all()
    return [
        workflow_impact(
            workflow_id=str(workflow.id),
            workflow_name=workflow.name,
            node_names=by_workflow.get(workflow.id, []),
            targeted=targeted,
            reason="This workflow runs against the dataset",
        )
        for workflow in workflows
    ]


def dataset_columns(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> list[str]:
    ensure_owned_project(db, project_id, current_user.id)
    return _dataset_columns(_get_dataset(db, project_id, dataset_id))


def dataset_column_types(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> dict[str, str]:
    """Each column's inferred type, for callers choosing a sensible default."""
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)

    for candidate in (dataset.schema_json, dataset.schema_snapshot):
        if not isinstance(candidate, dict):
            continue
        entries = candidate.get("columns")
        if isinstance(entries, list) and entries:
            return {
                str(entry["name"]): str(entry.get("inferred_type") or "unknown")
                for entry in entries
                if isinstance(entry, dict) and entry.get("name")
            }
    return {}


def total_traceable_datasets(db: Session, project_id: uuid.UUID | None = None) -> int:
    statement = select(Dataset).where(Dataset.is_derived.is_(True))
    if project_id is not None:
        statement = statement.where(Dataset.project_id == project_id)
    return len(db.scalars(statement).all())
