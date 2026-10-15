"""Recipe snapshots, so a suggested change has a "before" and can be applied.

Governance keeps versions and change requests but has no idea what a recipe
is. Until C2 it had nothing to ask: a proposed recipe change had no "before",
its summary read "Changed .", and approving one failed because nothing could
write it back. These two functions read a recipe into a document and write a
document back over it, the way `service_workflows.versioning` does for
workflows. Registered on import; the gateway imports this module.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_transformations.models import TransformationPipeline

RESOURCE_TYPE = "pipeline"


def snapshot_recipe(db: Session, project_id: uuid.UUID, recipe_id: uuid.UUID) -> dict[str, Any] | None:
    """The parts of a recipe a person changes: its name, notes, steps and parameters."""
    recipe = db.scalar(
        select(TransformationPipeline).where(
            TransformationPipeline.id == recipe_id, TransformationPipeline.project_id == project_id
        )
    )
    if recipe is None:
        return None
    return {
        "name": recipe.name,
        "description": recipe.description,
        "steps_json": list(recipe.steps_json or []),
        "parameters": list(recipe.parameters_json or []),
    }


def apply_recipe_snapshot(
    db: Session,
    project_id: uuid.UUID,
    recipe_id: uuid.UUID,
    snapshot: dict[str, Any],
    actor_user_id: uuid.UUID | None,
    reason: str | None = None,
) -> None:
    """Write a document back over a recipe, as its next revision.

    The steps are checked as any save's are. The Studio's shared copy starts
    again from the result, saying why, because this change was made outside
    it.
    """
    from service_transformations.coedit import record_save
    from service_transformations.validators import validate_steps_json

    recipe = db.scalar(
        select(TransformationPipeline).where(
            TransformationPipeline.id == recipe_id, TransformationPipeline.project_id == project_id
        )
    )
    if recipe is None:
        return
    if "name" in snapshot and snapshot["name"]:
        recipe.name = str(snapshot["name"])[:160]
    if "description" in snapshot:
        recipe.description = snapshot.get("description")
    if "steps_json" in snapshot:
        recipe.steps_json = [step.model_dump(mode="json") for step in validate_steps_json(snapshot["steps_json"] or [])]
    if "parameters" in snapshot:
        from service_transformations.parameters import validate

        recipe.parameters_json = [p.model_dump(mode="json") for p in validate(snapshot["parameters"] or [])] or None
    actor = _actor(db, actor_user_id)
    record_save(
        db,
        recipe,
        actor,
        step_ids=None,
        from_shared_epoch=None,
        reason=reason or f"{actor.username if actor else 'Someone'} changed this recipe from its history.",
    )
    db.flush()


def _actor(db: Session, user_id: uuid.UUID | None):
    if user_id is None:
        return None
    from service_auth.models import User
    from service_auth.schemas import UserRead

    user = db.get(User, user_id)
    return UserRead.model_validate(user) if user is not None else None


def record_recipe_version(db: Session, recipe: TransformationPipeline, actor_user_id: uuid.UUID | None) -> None:
    """Keep the recipe as it now is in its history. Best effort: a gap in
    history is bad, a save that failed because of one is worse."""
    try:
        from service_governance.versions import record_version

        snapshot = snapshot_recipe(db, recipe.project_id, recipe.id)
        if snapshot is None:
            return
        record_version(
            db,
            project_id=recipe.project_id,
            resource_type=RESOURCE_TYPE,
            resource_id=recipe.id,
            name=recipe.name,
            snapshot=snapshot,
            actor_user_id=actor_user_id,
        )
    except ImportError:  # pragma: no cover - governance is optional at import time
        return


def _signature(step: dict[str, Any]) -> str:
    import json

    return f"{step.get('step_type')}|{json.dumps(step.get('config') or {}, sort_keys=True, default=str)}"


def _step_words(step: dict[str, Any]) -> str:
    return str(step.get("step_type") or "step").replace("_", " ")


def describe_recipe_change(before: dict[str, Any] | None, after: dict[str, Any]) -> str:
    """What changed in a recipe, in a sentence or two (C2).

    The generic snapshot diff says "Added steps json[step type=sort rows]";
    this says "Adds a sort rows step." Steps that stay the same are found
    first (the longest run they share); one that only changed place moved;
    the nearest added step of the same kind as a removed one changed.
    """
    if before is None:
        return "Created."
    parts: list[str] = []
    if (before.get("name") or "").strip() != (after.get("name") or "").strip():
        parts.append(f"Renames it to “{(after.get('name') or '').strip()}”.")
    old_steps = list(before.get("steps_json") or [])
    new_steps = list(after.get("steps_json") or [])
    old_keys = [_signature(step) for step in old_steps]
    new_keys = [_signature(step) for step in new_steps]
    # Longest common subsequence, earlier steps keeping their places on ties.
    table = [[0] * (len(new_keys) + 1) for _ in range(len(old_keys) + 1)]
    for i in range(len(old_keys) - 1, -1, -1):
        for j in range(len(new_keys) - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if old_keys[i] == new_keys[j] else max(table[i + 1][j], table[i][j + 1])
    kept_old, kept_new = set(), set()
    i = j = 0
    while i < len(old_keys) and j < len(new_keys):
        if old_keys[i] == new_keys[j]:
            kept_old.add(i)
            kept_new.add(j)
            i += 1
            j += 1
        elif table[i + 1][j] > table[i][j + 1]:
            i += 1
        else:
            j += 1
    removed = [index for index in range(len(old_steps)) if index not in kept_old]
    added = [index for index in range(len(new_steps)) if index not in kept_new]
    for gone in removed:
        moved = next((index for index in added if new_keys[index] == old_keys[gone]), None)
        if moved is not None:
            parts.append(f"Moves the {_step_words(old_steps[gone])} step from step {gone + 1} to step {moved + 1}.")
            added.remove(moved)
            continue
        same_kind = [index for index in added if new_steps[index].get("step_type") == old_steps[gone].get("step_type")]
        if same_kind:
            changed = min(same_kind, key=lambda index: abs(index - gone))
            parts.append(f"Changes the {_step_words(new_steps[changed])} step (step {changed + 1}).")
            added.remove(changed)
            continue
        parts.append(f"Removes the {_step_words(old_steps[gone])} step (step {gone + 1}).")
    for index in added:
        parts.append(f"Adds a {_step_words(new_steps[index])} step (step {index + 1}).")
    if (before.get("description") or "") != (after.get("description") or ""):
        parts.append("Changes its description.")
    if (before.get("parameters") or []) != (after.get("parameters") or []):
        parts.append("Changes its parameters.")
    if not parts:
        return "No change to its steps."
    if len(parts) > 3:
        return " ".join(parts[:3]) + f" And {len(parts) - 3} more."
    return " ".join(parts)


def register() -> None:
    """Teach governance how to read, write and describe a recipe."""
    try:
        from service_governance.versions import register_restorer, register_snapshotter, register_summariser

        register_snapshotter(RESOURCE_TYPE, snapshot_recipe)
        register_restorer(RESOURCE_TYPE, apply_recipe_snapshot)
        register_summariser(RESOURCE_TYPE, describe_recipe_change)
    except ImportError:  # pragma: no cover - governance is optional at import time
        pass


register()
