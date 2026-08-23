"""Execution context for steps that need more than the working frame.

Single-frame steps (filter, cast, trim, ...) are pure functions of the frame.
Join and union additionally need to load another dataset, which requires the
database session and storage backend. Rather than threading those through every
step signature, multi-input steps receive a `StepContext` carrying a resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from shared_python.errors import BadRequestError


@dataclass(frozen=True)
class StepContext:
    """Resolves sibling datasets for multi-input steps."""

    resolve_dataset: Callable[[str], pd.DataFrame] | None = None
    describe_dataset: Callable[[str], str] | None = None

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        if self.resolve_dataset is None:
            raise BadRequestError(
                "This step reads another dataset, which is not available in the current context."
            )
        return self.resolve_dataset(dataset_id)

    def dataset_label(self, dataset_id: str) -> str:
        if self.describe_dataset is None:
            return dataset_id
        try:
            return self.describe_dataset(dataset_id)
        except Exception:  # noqa: BLE001 - a label is cosmetic; never fail a run over it
            return dataset_id


ContextStepApplyFn = Callable[[pd.DataFrame, dict[str, Any], StepContext], tuple[pd.DataFrame, list[str]]]
