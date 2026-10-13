"""Every audited route reads as a sentence (adoption-readiness A5)."""

from __future__ import annotations

import re
import uuid

from api_gateway.main import app
from service_governance.audit import is_audited
from service_governance.audit_words import summarise

SOME_ID = "00000000-0000-4000-8000-000000000001"


def _audited_routes() -> list[tuple[str, str]]:
    routes = []
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            concrete = re.sub(r"\{[^}]+\}", SOME_ID, path)
            if is_audited(method.upper(), concrete):
                routes.append((method.upper(), concrete))
    return routes


def test_there_are_audited_routes_to_describe() -> None:
    assert len(_audited_routes()) > 100


def test_every_audited_route_has_words_of_its_own() -> None:
    vague = [f"{method} {path}" for method, path in _audited_routes() if summarise(method, path).endswith("something")]
    assert vague == []


def test_no_summary_shows_a_path_or_a_code_name() -> None:
    for method, path in _audited_routes():
        words = summarise(method, path)
        assert "/" not in words and "{" not in words and "_" not in words, (method, path, words)
        assert not re.search(r"\b(pipeline|extraction|publish|materiali[sz]e)\b", words), (method, path, words)


def test_examples_read_as_people_would_say_them() -> None:
    project = f"/api/v1/projects/{uuid.uuid4()}"
    assert summarise("POST", f"{project}/pipelines/{uuid.uuid4()}/run") == "ran a recipe"
    assert summarise("DELETE", f"{project}/dashboards/{uuid.uuid4()}") == "deleted a dashboard"
    assert summarise("PATCH", f"{project}/data-quality/rules/{uuid.uuid4()}") == "changed a check"
    assert summarise("POST", f"{project}/datasets/{uuid.uuid4()}/deliver") == "delivered a dataset"
    assert summarise("DELETE", project) == "deleted the project"
