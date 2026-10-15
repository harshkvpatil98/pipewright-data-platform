"""Suggesting a change to a recipe instead of saving it (C2).

Someone who may not edit a recipe (a viewer or an operator), or anyone in a
project whose changes need approval, turns what they changed in the Studio
into a change request. Editors see it in the Studio and under Approvals,
compare the steps, and accept it (written to the recipe as its next
revision, through the recipe's restorer) or decline it with a note. It is
the same change request a person could make by hand, so everything about
reviewing one applies.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from service_transformations.contracts import get_transformation_pipeline_for_project
from service_transformations.validators import validate_steps_json

#: Who is asked to review a suggestion: everyone who may apply it.
REVIEWERS = ("editor", "admin")


class RecipeSuggestion(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    steps_json: list[dict[str, Any]] = Field(default_factory=list)


def suggest_change(
    db: Session,
    project_id: uuid.UUID,
    recipe_id: uuid.UUID,
    payload: RecipeSuggestion,
    current_user: UserRead,
):
    """Make a change request from a suggested recipe, and ask its reviewers."""
    from service_governance.schemas import ChangeRequestCreate
    from service_governance.service import propose_change

    ensure_owned_project(db, project_id, current_user.id)
    recipe = get_transformation_pipeline_for_project(db, project_id, recipe_id)
    steps = [step.model_dump(mode="json") for step in validate_steps_json(payload.steps_json)]
    after = {
        "name": (payload.name or recipe.name).strip()[:160],
        "description": recipe.description,
        "steps_json": steps,
        # A suggestion is of steps; the parameters stay as they are (E1).
        "parameters": list(recipe.parameters_json or []),
    }
    detail = propose_change(
        db,
        project_id,
        ChangeRequestCreate(
            resource_type="pipeline",
            resource_id=recipe.id,
            title=payload.title.strip(),
            description=(payload.note or "").strip() or None,
            after_json=after,
        ),
        current_user,
    )
    _ask_reviewers(db, project_id, recipe.id, recipe.name, payload.title.strip(), current_user)
    db.commit()
    return detail


def _ask_reviewers(
    db: Session, project_id: uuid.UUID, recipe_id: uuid.UUID, recipe_name: str, title: str, author: UserRead
) -> None:
    from service_access.models import ProjectMembership
    from service_notifications.service import create_user_notification
    from service_projects.models import Project

    project = db.get(Project, project_id)
    people = set(
        db.scalars(
            select(ProjectMembership.user_id).where(
                ProjectMembership.project_id == project_id, ProjectMembership.role.in_(REVIEWERS)
            )
        ).all()
    )
    if project is not None and project.owner_user_id:
        people.add(project.owner_user_id)
    people.discard(author.id)
    for user_id in sorted(people, key=str):
        create_user_notification(
            db,
            user_id=user_id,
            project_id=project_id,
            type="suggestion",
            level="info",
            title=f"A suggestion for {recipe_name}",
            message=f"{author.username} suggested “{title}”. Open the recipe or Approvals to accept or decline it.",
            related_pipeline_id=recipe_id,
        )
