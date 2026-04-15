import uuid
from types import SimpleNamespace

import pytest

from service_projects.contracts import ensure_owned_project
from shared_python.errors import NotFoundError


class FakeDb:
    def __init__(self, project):
        self.project = project

    def scalar(self, _statement):
        return self.project


def test_ensure_owned_project_returns_project_for_owner() -> None:
    project = SimpleNamespace(id=uuid.uuid4())
    db = FakeDb(project)
    assert ensure_owned_project(db, uuid.uuid4(), uuid.uuid4()) is project


def test_ensure_owned_project_hides_foreign_projects() -> None:
    db = FakeDb(None)
    with pytest.raises(NotFoundError):
        ensure_owned_project(db, uuid.uuid4(), uuid.uuid4())
