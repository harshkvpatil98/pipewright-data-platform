import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from service_auth.schemas import UserRead
from service_pipeline_runs.service import create_sample_pipeline_run, list_pipeline_runs


class _StubPipelineRun:
    """Lightweight stand-in so tests avoid configuring the full SQLAlchemy relationship graph."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)
        self.id = None


class FakeScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeDb:
    def __init__(self):
        self.added = None

    def add(self, obj):
        self.added = obj

    def flush(self):
        if self.added.id is None:
            self.added.id = uuid.uuid4()

    def commit(self):
        pass

    def refresh(self, obj):
        now = datetime.now(UTC)
        obj.created_at = now
        obj.updated_at = now
        obj.triggered_by_username = "platform-admin"

    def scalars(self, _statement):
        run = SimpleNamespace(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            triggered_by_user_id=uuid.uuid4(),
            pipeline_id=None,
            triggered_by_username="platform-admin",
            run_type="sample_orchestration",
            status="succeeded",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            summary_json={"project_status": "active"},
            logs_json={"events": []},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        return FakeScalarResult([run])


@patch("service_pipeline_runs.service.PipelineRun", _StubPipelineRun)
@patch("service_pipeline_runs.service.ensure_owned_project")
@patch("service_pipeline_runs.service.count_project_sources", return_value=2)
@patch("service_pipeline_runs.service.count_project_datasets", return_value=3)
@patch("service_pipeline_runs.service.count_project_runs", return_value=4)
@patch("service_pipeline_runs.service.total_sources", return_value=7)
def test_create_sample_pipeline_run_persists_summary(
    _total_sources,
    _count_project_runs,
    _count_project_datasets,
    _count_project_sources,
    ensure_owned_project,
) -> None:
    project = SimpleNamespace(id=uuid.uuid4(), slug="finance-quality", status="active")
    ensure_owned_project.return_value = project
    db = FakeDb()
    user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    run = create_sample_pipeline_run(db, project.id, user)

    assert run.status == "succeeded"
    assert run.summary_json["project_slug"] == "finance-quality"
    assert run.summary_json["project_run_count"] == 5


@patch("service_pipeline_runs.service.ensure_owned_project")
def test_list_pipeline_runs_returns_items(_ensure_owned_project) -> None:
    db = FakeDb()
    user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    response = list_pipeline_runs(db, uuid.uuid4(), user)
    assert len(response.items) == 1
