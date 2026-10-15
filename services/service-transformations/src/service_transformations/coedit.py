"""Editing a recipe together (roadmap Phase 21, C2).

Everyone with a recipe open in the Studio edits one shared copy of it. The
copy is a small CRDT, so changes merge the same whatever order they arrive
in, and nobody's work is written over:

- steps are a sequence of stable ids, ordered by a fractional position (a
  string that sorts between its neighbours) and then by id;
- each of a step's settings, its position, whether it is removed, and the
  recipe's name, is a last-writer-wins register;
- a removed step is a tombstone, so a late change to it is harmless and an
  undo can bring it back;
- every change carries a Lamport stamp `[counter, client]`, compared as a
  pair, so "last" means the same thing on every machine.

The server keeps the merged copy (`RecipeSharedCopy.doc_json`) and the
changes in the order they arrived (`RecipeEditBatch`), so a Studio asks
only for what is new. The Studio's own copy of these rules is
`apps/web/src/features/studio/coedit.ts`; `coedit-fixtures.json` holds
cases both must agree on.

Saving writes the shared copy to the recipe as its next revision. Anything
that changes a recipe some other way (a restored version, an approved
suggestion, the API) starts the copy again from the saved recipe, in a new
epoch, and says why.
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, ConflictError
from service_transformations.contracts import get_transformation_pipeline_for_project
from service_transformations.models import RecipeEditBatch, RecipeSharedCopy, TransformationPipeline

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
SEED_CLIENT = "saved"
#: How many batches of changes are kept; a Studio further behind reloads.
KEEP_BATCHES = 1000
MAX_OPS_PER_BATCH = 500
MAX_BATCH_BYTES = 512_000
MAX_ID = 64

Stamp = list  # [counter: int, client: str]


# --------------------------------------------------------------------------
# Positions
# --------------------------------------------------------------------------


def between(low: str | None, high: str | None) -> str:
    """A position that sorts after `low` and before `high` (None: open end).

    Positions are base-36 fractions written without the "0.": "m" is about a
    half, "8" about a fifth. A position never ends in "0", so one is never a
    prefix of another with only zeros after it, and there is always room.
    """
    low = low or ""
    if high is not None and high <= low:
        raise ValueError("between() needs low < high")
    result = ""
    index = 0
    upper: str | None = high
    while True:
        a = DIGITS.index(low[index]) if index < len(low) else 0
        b = DIGITS.index(upper[index]) if upper is not None and index < len(upper) else len(DIGITS)
        if b - a > 1:
            return result + DIGITS[(a + b) // 2]
        result += DIGITS[a]
        if b - a == 1:
            # Past this digit the upper bound no longer constrains us.
            upper = None
        index += 1


# --------------------------------------------------------------------------
# The merge
# --------------------------------------------------------------------------


def _newer(candidate: Stamp, current: Stamp | None) -> bool:
    if current is None:
        return True
    return (int(candidate[0]), str(candidate[1])) > (int(current[0]), str(current[1]))


def _register(value: Any, stamp: Stamp, *, absent: bool = False) -> dict[str, Any]:
    register: dict[str, Any] = {"v": value, "s": [int(stamp[0]), str(stamp[1])]}
    if absent:
        register["x"] = True
    return register


def _merge(target: dict[str, Any], key: str, register: dict[str, Any]) -> None:
    current = target.get(key)
    if current is None or _newer(register["s"], current.get("s")):
        target[key] = register


def empty_doc() -> dict[str, Any]:
    return {"name": None, "steps": {}}


def _step(doc: dict[str, Any], step_id: str) -> dict[str, Any]:
    steps = doc.setdefault("steps", {})
    if step_id not in steps:
        # A change can arrive for a step whose adding has not: it waits in a
        # step with no type, which is not shown until the add arrives.
        steps[step_id] = {"type": None, "pos": None, "del": None, "cfg": {}}
    return steps[step_id]


def apply_op(doc: dict[str, Any], op: dict[str, Any]) -> None:
    """Merge one change into `doc`, in place. Order does not matter."""
    kind = op.get("k")
    stamp = op.get("s")
    if kind == "name":
        _merge(doc, "name", _register(op.get("v"), stamp))
        return
    step = _step(doc, str(op["id"]))
    if kind == "add":
        if step["type"] is None:
            step["type"] = op["type"]
        _merge(step, "pos", _register(op["pos"], stamp))
        _merge(step, "del", _register(False, stamp))
        for key, value in (op.get("cfg") or {}).items():
            _merge(step["cfg"], key, _register(value, stamp))
    elif kind == "set":
        _merge(step["cfg"], str(op["key"]), _register(op.get("v"), stamp, absent=bool(op.get("x"))))
    elif kind == "move":
        _merge(step, "pos", _register(op["pos"], stamp))
    elif kind == "del":
        _merge(step, "del", _register(bool(op.get("v", True)), stamp))
    else:
        raise BadRequestError(f"“{kind}” is not a change a recipe can take.")


def apply_ops(doc: dict[str, Any], ops: Iterable[dict[str, Any]]) -> dict[str, Any]:
    merged = copy.deepcopy(doc)
    for op in ops:
        apply_op(merged, op)
    return merged


def materialise(doc: dict[str, Any]) -> dict[str, Any]:
    """The recipe the copy describes: its name and its steps, in order."""
    visible = []
    for step_id, step in (doc.get("steps") or {}).items():
        if step.get("type") is None or step.get("pos") is None:
            continue
        if (step.get("del") or {}).get("v", False):
            continue
        config = {key: register["v"] for key, register in sorted(step["cfg"].items()) if not register.get("x")}
        visible.append((step["pos"]["v"], step_id, {"id": step_id, "step_type": step["type"], "config": config}))
    visible.sort(key=lambda item: (item[0], item[1]))
    name = doc.get("name")
    return {"name": name["v"] if name else None, "steps": [item[2] for item in visible]}


def seed(name: str, steps: list[dict[str, Any]], step_ids: list[str]) -> dict[str, Any]:
    """A copy holding exactly the saved recipe, stamped before any change."""
    doc = empty_doc()
    stamp: Stamp = [0, SEED_CLIENT]
    apply_op(doc, {"k": "name", "v": name, "s": stamp})
    position: str | None = None
    for step_id, step in zip(step_ids, steps, strict=True):
        position = between(position, None)
        apply_op(
            doc,
            {"k": "add", "id": step_id, "type": step["step_type"], "pos": position, "cfg": step.get("config") or {}, "s": stamp},
        )
    return doc


def max_counter(doc: dict[str, Any]) -> int:
    """The highest stamp counter in a copy, so a Studio's clock starts past it."""
    highest = 0
    name = doc.get("name")
    if name:
        highest = max(highest, int(name["s"][0]))
    for step in (doc.get("steps") or {}).values():
        for register in (step.get("pos"), step.get("del")):
            if register:
                highest = max(highest, int(register["s"][0]))
        for register in step.get("cfg", {}).values():
            highest = max(highest, int(register["s"][0]))
    return highest


# --------------------------------------------------------------------------
# What a change may look like
# --------------------------------------------------------------------------


def _check(ops: list[dict[str, Any]]) -> None:
    if len(ops) > MAX_OPS_PER_BATCH:
        raise BadRequestError(f"Send at most {MAX_OPS_PER_BATCH} changes at a time.")
    if len(json.dumps(ops, default=str)) > MAX_BATCH_BYTES:
        raise BadRequestError("These changes are too large to send at once.")
    for op in ops:
        if not isinstance(op, dict):
            raise BadRequestError("Each change must be an object.")
        stamp = op.get("s")
        if (
            not isinstance(stamp, list)
            or len(stamp) != 2
            or not isinstance(stamp[0], int)
            or isinstance(stamp[0], bool)
            or stamp[0] < 1
            or not isinstance(stamp[1], str)
            or not 0 < len(stamp[1]) <= MAX_ID
            or stamp[1] == SEED_CLIENT
        ):
            raise BadRequestError("A change is missing its stamp.")
        kind = op.get("k")
        if kind == "name":
            if not isinstance(op.get("v"), str) or len(op["v"]) > 160:
                raise BadRequestError("A recipe's name is text of 160 characters or fewer.")
            continue
        step_id = op.get("id")
        if not isinstance(step_id, str) or not 0 < len(step_id) <= MAX_ID:
            raise BadRequestError("A change must name the step it is about.")
        if kind == "add":
            if not isinstance(op.get("type"), str) or not op["type"]:
                raise BadRequestError("An added step needs a type.")
            if not isinstance(op.get("cfg") or {}, dict):
                raise BadRequestError("An added step's settings must be an object.")
            _check_position(op.get("pos"))
        elif kind == "set":
            if not isinstance(op.get("key"), str) or not 0 < len(op["key"]) <= 128:
                raise BadRequestError("A changed setting needs its name.")
        elif kind == "move":
            _check_position(op.get("pos"))
        elif kind == "del":
            if not isinstance(op.get("v", True), bool):
                raise BadRequestError("Removing a step is true or false.")
        else:
            raise BadRequestError(f"“{kind}” is not a change a recipe can take.")


def _check_position(position: Any) -> None:
    if (
        not isinstance(position, str)
        or not 0 < len(position) <= 128
        or any(character not in DIGITS for character in position)
        or position.endswith("0")
    ):
        raise BadRequestError("A step's place in the recipe is not one this server can read.")


# --------------------------------------------------------------------------
# The shared copy
# --------------------------------------------------------------------------


class EditBatchRead(BaseModel):
    seq: int
    client_id: str
    actor: str | None
    ops: list[dict[str, Any]]


class SavedRecipeRead(BaseModel):
    revision: int
    name: str
    steps_json: list[dict[str, Any]]
    step_ids: list[str]
    revised_by: str | None
    revised_at: datetime | None


class SharedCopyRead(BaseModel):
    """What a Studio needs to catch up with everyone else."""

    epoch: int
    seq: int
    #: The whole merged copy, when the Studio is new, behind or in an old epoch.
    doc: dict[str, Any] | None = None
    #: Otherwise, the changes since the Studio last asked.
    batches: list[EditBatchRead] = Field(default_factory=list)
    #: The saved recipe, when it is newer than the revision the Studio named.
    saved: SavedRecipeRead | None = None
    revision: int
    #: Why the copy started again, when the Studio was in an older epoch.
    reset_reason: str | None = None
    your_role: str | None = None
    #: Changes to this recipe that need someone else's approval.
    needs_approval: bool = False
    open_suggestions: int = 0


class SharedCopyPush(BaseModel):
    epoch: int = Field(ge=1)
    client_id: str = Field(min_length=1, max_length=MAX_ID)
    ops: list[dict[str, Any]] = Field(default_factory=list)


class SharedCopyPushResult(BaseModel):
    epoch: int
    seq: int


def ensure_step_ids(pipeline: TransformationPipeline) -> list[str]:
    """The recipe's step ids, made for a recipe saved before they existed."""
    steps = pipeline.steps_json or []
    ids = list(pipeline.step_ids_json or [])
    if len(ids) != len(steps) or len(set(ids)) != len(ids):
        ids = [uuid.uuid4().hex for _ in steps]
        pipeline.step_ids_json = ids
    return ids


def _copy_for(db: Session, pipeline: TransformationPipeline, *, lock: bool = False) -> RecipeSharedCopy:
    statement = select(RecipeSharedCopy).where(RecipeSharedCopy.pipeline_id == pipeline.id)
    if lock:
        statement = statement.with_for_update()
    shared = db.scalar(statement)
    if shared is None:
        # Two Studios opening a recipe together both find no copy; the second
        # to write finds the first's rather than failing on the constraint.
        try:
            with db.begin_nested():
                db.add(
                    RecipeSharedCopy(
                        project_id=pipeline.project_id,
                        pipeline_id=pipeline.id,
                        epoch=1,
                        seq=0,
                        doc_json=seed(pipeline.name, pipeline.steps_json or [], ensure_step_ids(pipeline)),
                    )
                )
        except IntegrityError:
            pass
        shared = db.scalar(statement)
    return shared


def start_again(db: Session, pipeline: TransformationPipeline, reason: str) -> None:
    """After a change made outside the Studio: the copy starts from the
    saved recipe in a new epoch, and the old changes go."""
    shared = db.scalar(select(RecipeSharedCopy).where(RecipeSharedCopy.pipeline_id == pipeline.id))
    if shared is None:
        return
    shared.epoch = int(shared.epoch) + 1
    shared.doc_json = seed(pipeline.name, pipeline.steps_json or [], ensure_step_ids(pipeline))
    shared.reset_reason = reason[:500]
    db.execute(delete(RecipeEditBatch).where(RecipeEditBatch.pipeline_id == pipeline.id))


def _names(db: Session, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    from service_auth.models import User

    wanted = {value for value in ids if value is not None}
    if not wanted:
        return {}
    rows = db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(wanted))).all()
    return {row[0]: row[1] or row[2] for row in rows}


def saved_read(db: Session, pipeline: TransformationPipeline) -> SavedRecipeRead:
    names = _names(db, [pipeline.revised_by_user_id])
    return SavedRecipeRead(
        revision=int(pipeline.revision or 1),
        name=pipeline.name,
        steps_json=list(pipeline.steps_json or []),
        step_ids=ensure_step_ids(pipeline),
        revised_by=names.get(pipeline.revised_by_user_id) if pipeline.revised_by_user_id else None,
        revised_at=pipeline.revised_at,
    )


def _open_suggestions(db: Session, pipeline: TransformationPipeline) -> int:
    from service_governance.models import ChangeRequest

    return int(
        db.scalar(
            select(func.count(ChangeRequest.id)).where(
                ChangeRequest.resource_type == "pipeline",
                ChangeRequest.resource_id == pipeline.id,
                ChangeRequest.status == "open",
            )
        )
        or 0
    )


def read_shared(
    db: Session,
    project_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    current_user: UserRead,
    *,
    epoch: int | None,
    after: int | None,
    revision: int | None,
) -> SharedCopyRead:
    """The shared copy, or what changed in it since `after` in `epoch`."""
    from service_projects.contracts import project_role
    from service_projects.models import Project

    project = ensure_owned_project(db, project_id, current_user.id)
    pipeline = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    shared = _copy_for(db, pipeline)
    db.commit()

    full = epoch != shared.epoch or after is None
    batches: list[RecipeEditBatch] = []
    if not full:
        oldest = db.scalar(
            select(func.min(RecipeEditBatch.seq)).where(RecipeEditBatch.pipeline_id == pipeline.id)
        )
        if after < shared.seq and (oldest is None or oldest > after + 1):
            full = True  # what it missed is no longer kept
        else:
            batches = list(
                db.scalars(
                    select(RecipeEditBatch)
                    .where(RecipeEditBatch.pipeline_id == pipeline.id, RecipeEditBatch.seq > after)
                    .order_by(RecipeEditBatch.seq)
                ).all()
            )
    names = _names(db, [batch.actor_user_id for batch in batches])
    governed = bool(getattr(db.get(Project, project.id), "requires_approval", False))
    return SharedCopyRead(
        epoch=shared.epoch,
        seq=shared.seq,
        doc=copy.deepcopy(shared.doc_json) if full else None,
        batches=[
            EditBatchRead(
                seq=batch.seq,
                client_id=batch.client_id,
                actor=names.get(batch.actor_user_id) if batch.actor_user_id else None,
                ops=batch.ops_json,
            )
            for batch in batches
        ],
        saved=saved_read(db, pipeline) if revision is None or revision != int(pipeline.revision or 1) else None,
        revision=int(pipeline.revision or 1),
        reset_reason=shared.reset_reason if epoch is not None and epoch != shared.epoch else None,
        your_role=project_role(db, project_id, current_user.id),
        needs_approval=governed,
        open_suggestions=_open_suggestions(db, pipeline),
    )


def push_changes(
    db: Session,
    project_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    payload: SharedCopyPush,
    current_user: UserRead,
) -> SharedCopyPushResult:
    """Merge one Studio's changes into the shared copy, in arrival order."""
    ensure_owned_project(db, project_id, current_user.id)
    pipeline = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    _check(payload.ops)
    shared = _copy_for(db, pipeline, lock=True)
    if payload.epoch != shared.epoch:
        raise ConflictError(
            "This recipe was changed outside the Studio since you opened it, so the shared copy started again. "
            "The Studio has reloaded it."
        )
    if not payload.ops:
        return SharedCopyPushResult(epoch=shared.epoch, seq=shared.seq)
    shared.doc_json = apply_ops(shared.doc_json or empty_doc(), payload.ops)
    shared.seq = int(shared.seq) + 1
    db.add(
        RecipeEditBatch(
            pipeline_id=pipeline.id,
            epoch=shared.epoch,
            seq=shared.seq,
            client_id=payload.client_id,
            actor_user_id=current_user.id,
            ops_json=payload.ops,
        )
    )
    db.flush()
    kept_from = shared.seq - KEEP_BATCHES
    if kept_from > 0:
        db.execute(
            delete(RecipeEditBatch).where(RecipeEditBatch.pipeline_id == pipeline.id, RecipeEditBatch.seq <= kept_from)
        )
    db.commit()
    return SharedCopyPushResult(epoch=shared.epoch, seq=shared.seq)


def discard_unsaved(
    db: Session, project_id: uuid.UUID, pipeline_id: uuid.UUID, current_user: UserRead
) -> SharedCopyRead:
    """Throw away the shared copy's unsaved changes, for everyone."""
    ensure_owned_project(db, project_id, current_user.id)
    pipeline = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    _copy_for(db, pipeline, lock=True)
    start_again(db, pipeline, f"{current_user.username} discarded the unsaved changes.")
    db.commit()
    return read_shared(db, project_id, pipeline_id, current_user, epoch=None, after=None, revision=None)


def check_save(
    db: Session,
    pipeline: TransformationPipeline,
    *,
    expected_revision: int | None,
) -> None:
    """Refuse a save that started from an older revision than the recipe's."""
    current = int(pipeline.revision or 1)
    if expected_revision is None or expected_revision == current:
        return
    names = _names(db, [pipeline.revised_by_user_id])
    who = names.get(pipeline.revised_by_user_id) if pipeline.revised_by_user_id else None
    when = pipeline.revised_at.astimezone(UTC).strftime("%-d %b %Y, %H:%M UTC") if pipeline.revised_at else None
    detail = f"{who or 'Someone'} saved this recipe"
    if when:
        detail += f" at {when}"
    detail += " after you opened it, so saving now would replace their changes. Open it again to see them, then save."
    raise ConflictError(detail)


def record_save(
    db: Session,
    pipeline: TransformationPipeline,
    current_user: UserRead | None,
    *,
    step_ids: list[str] | None,
    from_shared_epoch: int | None,
    reason: str | None = None,
) -> None:
    """Move a recipe to its next revision after its name or steps changed.

    A save from the Studio's shared copy (`from_shared_epoch` is its epoch)
    keeps the copy; any other change starts it again, saying why.
    """
    pipeline.revision = int(pipeline.revision or 1) + 1
    pipeline.revised_by_user_id = current_user.id if current_user else None
    pipeline.revised_at = datetime.now(UTC)
    steps = pipeline.steps_json or []
    if step_ids is not None and len(step_ids) == len(steps) and len(set(step_ids)) == len(step_ids) and all(
        isinstance(value, str) and 0 < len(value) <= MAX_ID for value in step_ids
    ):
        pipeline.step_ids_json = list(step_ids)
    else:
        pipeline.step_ids_json = [uuid.uuid4().hex for _ in steps]
    shared = db.scalar(select(RecipeSharedCopy).where(RecipeSharedCopy.pipeline_id == pipeline.id))
    if shared is None:
        return
    if from_shared_epoch is not None and from_shared_epoch == shared.epoch:
        return
    who = current_user.username if current_user else "Someone"
    start_again(db, pipeline, reason or f"{who} changed this recipe outside the Studio.")


Mode = Literal["live", "suggest"]
