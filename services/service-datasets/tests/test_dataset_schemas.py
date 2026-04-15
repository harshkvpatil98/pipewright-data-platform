import pytest
from pydantic import ValidationError

from service_datasets.schemas import DatasetCreate


def test_dataset_schema_accepts_null_profile_metrics() -> None:
    payload = DatasetCreate(name="Orders", row_count=None, column_count=None)
    assert payload.name == "Orders"


def test_dataset_schema_rejects_negative_counts() -> None:
    with pytest.raises(ValidationError):
        DatasetCreate(name="Orders", row_count=-1)
