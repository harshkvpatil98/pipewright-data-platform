from __future__ import annotations

import uuid

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
from service_projects.contracts import ensure_owned_project
from service_transformations.suggestion_rules import build_suggestions_for_dataset
from service_transformations.suggestion_schemas import DatasetTransformationSuggestionsResponse
from service_transformations.validators import validate_steps_json


def list_dataset_transformation_suggestions(
    db,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    current_user: UserRead,
) -> DatasetTransformationSuggestionsResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    raw = build_suggestions_for_dataset(
        dataset_id=dataset.id,
        project_id=project_id,
        schema_json=dataset.schema_json,
        profile_json=dataset.profile_json,
        preview_json=dataset.preview_json,
    )
    for suggestion in raw:
        validate_steps_json([{'step_type': suggestion.step_type, 'config': suggestion.config}])
    return DatasetTransformationSuggestionsResponse(
        dataset_id=dataset.id,
        project_id=project_id,
        suggestions=raw,
    )
