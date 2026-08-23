"""Promoting a resource from one environment to the next.

Environments are separate projects, so promotion is a copy: take the snapshot
that version history already knows how to produce, and write it into the target
project. That reuse is the whole design -- anything that can be versioned can
be promoted, and neither feature has to know what the other's resources are.

The interesting part is what a copy *cannot* carry. A workflow's configuration
names datasets, pipelines, and extraction jobs by id, and those ids belong to
the source project. Copying them verbatim would produce a workflow in
production that quietly reads from development. So references are re-pointed by
name, and anything that has no match in the target is reported rather than
guessed at.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError, NotFoundError

from service_governance.versions import _restorers, current_snapshot, record_version

# Config keys whose values are ids belonging to the source project.
REFERENCE_KEYS = (
    "dataset_id",
    "baseline_dataset_id",
    "right_dataset_id",
    "other_dataset_id",
    "pipeline_id",
    "extraction_job_id",
    "destination_id",
)

# resource_type -> a function creating an empty resource in a project and
# returning its id.
Creator = Callable[[Session, uuid.UUID, str, uuid.UUID | None], uuid.UUID]
_creators: dict[str, Creator] = {}

# A lookup from an id in the source project to the same-named thing in the
# target, per reference kind.
Resolver = Callable[[Session, uuid.UUID, uuid.UUID, uuid.UUID], uuid.UUID | None]
_resolvers: dict[str, Resolver] = {}


def register_creator(resource_type: str, creator: Creator) -> None:
    _creators[resource_type] = creator


def register_reference_resolver(reference_key: str, resolver: Resolver) -> None:
    _resolvers[reference_key] = resolver


@dataclass
class UnresolvedReference:
    key: str
    value: str
    where: str

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "value": self.value, "where": self.where}


@dataclass
class RemapResult:
    snapshot: dict[str, Any]
    unresolved: list[UnresolvedReference] = field(default_factory=list)


def remap_references(
    db: Session,
    snapshot: Any,
    *,
    source_project_id: uuid.UUID,
    target_project_id: uuid.UUID,
    where: str = "",
) -> RemapResult:
    """Re-point ids in a snapshot at the target project's equivalents."""
    result = RemapResult(snapshot=snapshot)

    if isinstance(snapshot, dict):
        rebuilt: dict[str, Any] = {}
        for key, value in snapshot.items():
            location = f"{where}.{key}" if where else key
            if key in REFERENCE_KEYS and isinstance(value, str) and value:
                replacement = _resolve(
                    db, key, value, source_project_id, target_project_id
                )
                if replacement is None:
                    result.unresolved.append(
                        UnresolvedReference(key=key, value=value, where=where or "config")
                    )
                    rebuilt[key] = None
                else:
                    rebuilt[key] = str(replacement)
                continue

            nested = remap_references(
                db,
                value,
                source_project_id=source_project_id,
                target_project_id=target_project_id,
                where=location,
            )
            rebuilt[key] = nested.snapshot
            result.unresolved.extend(nested.unresolved)
        result.snapshot = rebuilt
        return result

    if isinstance(snapshot, list):
        rebuilt_list = []
        for index, entry in enumerate(snapshot):
            nested = remap_references(
                db,
                entry,
                source_project_id=source_project_id,
                target_project_id=target_project_id,
                where=f"{where}[{index}]",
            )
            rebuilt_list.append(nested.snapshot)
            result.unresolved.extend(nested.unresolved)
        result.snapshot = rebuilt_list
        return result

    return result


def _resolve(
    db: Session,
    key: str,
    value: str,
    source_project_id: uuid.UUID,
    target_project_id: uuid.UUID,
) -> uuid.UUID | None:
    resolver = _resolvers.get(key)
    if resolver is None:
        return None
    try:
        return resolver(db, uuid.UUID(value), source_project_id, target_project_id)
    except (ValueError, TypeError):
        return None


def promote_resource(
    db: Session,
    *,
    source_project_id: uuid.UUID,
    target_project_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> tuple[uuid.UUID, list[UnresolvedReference], str]:
    """Copy one resource into another project."""
    if source_project_id == target_project_id:
        raise BadRequestError("A project cannot be promoted into itself.")

    creator = _creators.get(resource_type)
    restorer = _restorers.get(resource_type)
    if creator is None or restorer is None:
        raise BadRequestError(f"'{resource_type}' cannot be promoted.")

    snapshot = current_snapshot(db, resource_type, source_project_id, resource_id)
    if snapshot is None:
        raise NotFoundError("Nothing to promote.")

    remapped = remap_references(
        db,
        snapshot,
        source_project_id=source_project_id,
        target_project_id=target_project_id,
    )

    # Whatever arrives, arrives inert. A promoted workflow that started firing
    # on its old schedule the moment it landed in production would be the worst
    # possible outcome of a feature meant to make production safer -- and the
    # references it depends on may not even have matched.
    if isinstance(remapped.snapshot, dict) and "enabled" in remapped.snapshot:
        remapped.snapshot["enabled"] = False

    name = str(remapped.snapshot.get("name") or "Promoted")
    new_id = creator(db, target_project_id, name, actor_user_id)
    restorer(db, target_project_id, new_id, remapped.snapshot, actor_user_id)
    record_version(
        db,
        project_id=target_project_id,
        resource_type=resource_type,
        resource_id=new_id,
        name=name,
        snapshot=remapped.snapshot,
        actor_user_id=actor_user_id,
    )
    db.commit()

    if remapped.unresolved:
        summary = (
            f"Promoted '{name}', but {len(remapped.unresolved)} reference(s) had no match in the "
            "target project and were left empty. Fill them in before running it."
        )
    else:
        summary = f"Promoted '{name}'. Every reference matched something in the target project."

    return new_id, remapped.unresolved, summary


def find_by_name(model, name_attr: str = "name") -> Resolver:
    """A resolver that matches the source row's name in the target project."""

    def resolve(
        db: Session,
        source_id: uuid.UUID,
        source_project_id: uuid.UUID,
        target_project_id: uuid.UUID,
    ) -> uuid.UUID | None:
        source_row = db.scalar(
            select(model).where(model.id == source_id, model.project_id == source_project_id)
        )
        if source_row is None:
            return None
        match = db.scalar(
            select(model).where(
                model.project_id == target_project_id,
                getattr(model, name_attr) == getattr(source_row, name_attr),
            )
        )
        return match.id if match is not None else None

    return resolve
