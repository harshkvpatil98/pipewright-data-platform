from __future__ import annotations

from typing import Any

from service_transformations.contracts import SUPPORTED_TRANSFORMATION_STEP_TYPES
from service_transformations.schemas import TransformationStep
from shared_python.errors import BadRequestError

_STEP_REQUIRED_KEYS = {"step_type", "config"}


def validate_steps_json(steps_payload: Any) -> list[TransformationStep]:
    if not isinstance(steps_payload, list):
        raise BadRequestError("steps_json must be a list.")

    validated_steps: list[TransformationStep] = []
    for index, raw_step in enumerate(steps_payload):
        step_number = index + 1

        if not isinstance(raw_step, dict):
            raise BadRequestError(f"Step {step_number} must be an object.")
        if not raw_step:
            raise BadRequestError(f"Step {step_number} cannot be empty.")

        missing_keys = sorted(_STEP_REQUIRED_KEYS - set(raw_step.keys()))
        if missing_keys:
            raise BadRequestError(
                f"Step {step_number} is missing required field(s): {', '.join(missing_keys)}."
            )

        extra_keys = sorted(set(raw_step.keys()) - _STEP_REQUIRED_KEYS)
        if extra_keys:
            raise BadRequestError(
                f"Step {step_number} contains unsupported field(s): {', '.join(extra_keys)}."
            )

        step_type = raw_step["step_type"]
        if not isinstance(step_type, str) or not step_type.strip():
            raise BadRequestError(f"Step {step_number} must include a non-empty step_type.")
        if step_type not in SUPPORTED_TRANSFORMATION_STEP_TYPES:
            raise BadRequestError(
                f"Step {step_number} has unsupported step_type '{step_type}'. "
                f"Allowed values: {', '.join(SUPPORTED_TRANSFORMATION_STEP_TYPES)}."
            )

        config = raw_step["config"]
        if not isinstance(config, dict):
            raise BadRequestError(f"Step {step_number} config must be an object.")

        validated_steps.append(TransformationStep(step_type=step_type, config=config))

    return validated_steps


def normalize_pipeline_steps(steps_payload: Any) -> list[TransformationStep]:
    return validate_steps_json(steps_payload)
