from types import SimpleNamespace
from unittest.mock import patch

from service_projects.service import _slugify, _serialize_summary


def test_slugify_normalizes_strings() -> None:
    assert _slugify("Revenue Quality Monitoring") == "revenue-quality-monitoring"


@patch("service_projects.service.count_project_sources", return_value=3)
@patch("service_projects.service.count_project_datasets", return_value=4)
def test_serialize_summary_includes_counts(*_: object) -> None:
    project = SimpleNamespace(
        id="1c1bb0a6-a6b0-4aa1-aed2-5df11f0c8238",
        owner_user_id="9d0d2aa1-112e-4a76-9b80-fb52f8268d2a",
        name="Revenue Quality Monitoring",
        slug="revenue-quality-monitoring",
        description="Finance data quality workspace",
        status="active",
        environment="development",
        requires_approval=False,
        promoted_from_project_id=None,
        created_at="2026-04-02T00:00:00+00:00",
        updated_at="2026-04-02T00:00:00+00:00",
    )
    summary = _serialize_summary(project, 3, 4)
    assert summary.source_count == 3
    assert summary.dataset_count == 4
    assert summary.environment == "development"
