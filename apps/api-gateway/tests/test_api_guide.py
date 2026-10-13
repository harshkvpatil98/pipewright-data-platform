"""The API guide works as written (adoption-readiness A6, W3).

`docs/user/api.md` is what a person scripting Pipewright copies from. This
reads its `curl` examples and runs each one, in order, against the API: the
same method, address and body, with each `VAR=$(... | jq -r .path)` keeping
the answer for the next example. Every request the guide names must also
exist in the published reference. The one change: a SQLite file stands in
for the guide's PostgreSQL server, since there is none in a test.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_auth.models import User
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

GUIDE = Path(__file__).resolve().parents[3] / "docs" / "user" / "api.md"
USERNAME = "script-owner"
PASSWORD = "a-long-enough-password"

_CAPTURE = re.compile(r"^(\w+)=\$\(")
_METHOD = re.compile(r"-X (GET|POST|PATCH|PUT|DELETE)\b")
_URL = re.compile(r'"\$PIPEWRIGHT(/api/v1/[^"]*)"')
_BEARER = re.compile(r"Bearer \$(\w+)")
_JQ = re.compile(r"jq -r (\.[\w.]+)")
_INLINE = re.compile(r"`(GET|POST|PATCH|PUT|DELETE) (/api/v1/[^`\s]+)`")


def _examples() -> list[dict]:
    """Each `curl` command in the guide's code blocks, as a request to make."""
    blocks = re.findall(r"```bash\n(.*?)```", GUIDE.read_text(), flags=re.S)
    examples = []
    for block in blocks:
        if "curl" not in block:
            continue
        lines = block.splitlines()
        body = None
        if "<<EOF" in block:
            start = next(at for at, line in enumerate(lines) if "<<EOF" in line)
            end = next(at for at, line in enumerate(lines) if at > start and line.strip() == "EOF")
            body = "\n".join(lines[start + 1 : end])
        command = block if body is None else block.replace(body, "")
        url = _URL.search(command)
        assert url, f"a curl example has no $PIPEWRIGHT address:\n{block}"
        method = _METHOD.search(command)
        capture = _CAPTURE.search(command)
        jq = _JQ.search(command)
        bearer = _BEARER.search(command)
        examples.append({
            "method": method.group(1) if method else "GET",
            "url": url.group(1),
            "body": body,
            "capture": capture.group(1) if capture else None,
            "jq": jq.group(1) if jq else None,
            "bearer": bearer.group(1) if bearer else None,
        })
    return examples


def _shape(path: str) -> str:
    """`/projects/$PROJECT/runs` and `/projects/{project_id}/runs` both become `/projects/*/runs`."""
    path = path.split("?")[0]
    return "/".join("*" if part.startswith(("$", "{")) else part for part in path.split("/"))


def _fill(text: str, values: dict[str, str]) -> str:
    return re.sub(r"\$(\w+)", lambda match: values.get(match.group(1), match.group(0)), text)


def _pick(answer: dict, path: str):
    for key in path.strip(".").split("."):
        answer = answer[key]
    return answer


@pytest.fixture()
def api(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def _db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    # Some routers call the backend getter directly rather than through
    # Depends, so the backend itself is swapped, not the dependency.
    monkeypatch.setattr(dependencies, "storage_backend", LocalStorageBackend(str(tmp_path / "storage")))
    db = factory()
    db.add(User(username=USERNAME, password_hash=hash_password(PASSWORD), role="viewer", is_active=True))
    db.commit()
    db.close()
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_the_reference_loads(api) -> None:
    assert api.get("/docs").status_code == 200
    reference = api.get("/api/v1/openapi.json")
    assert reference.status_code == 200
    assert len(reference.json()["paths"]) > 100


def test_every_request_the_guide_names_exists() -> None:
    reference = app.openapi()["paths"]
    published = {(method.upper(), _shape(path)) for path, operations in reference.items() for method in operations}
    named = {(example["method"], _shape(example["url"])) for example in _examples()}
    named |= {(method, _shape(path)) for method, path in _INLINE.findall(GUIDE.read_text())}
    assert len(named) >= 10
    missing = sorted(named - published)
    assert not missing, f"the API guide names requests the API does not have: {missing}"


def test_the_worked_examples_run_as_written(api, tmp_path) -> None:
    source = tmp_path / "shop.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE orders (id INTEGER, customer TEXT, amount REAL)")
        connection.executemany(
            "INSERT INTO orders VALUES (?, ?, ?)",
            [(1, "ann", 10.0), (2, "bo", 30.0), (2, "bo", 30.0), (3, "cy", 20.0)],
        )

    values = {"USERNAME": USERNAME, "PASSWORD": PASSWORD, "DB_PASSWORD": "unused"}
    answers: list[tuple[dict, object]] = []
    for example in _examples():
        url = _fill(example["url"], values)
        headers = {}
        if example["bearer"]:
            headers["Authorization"] = f"Bearer {values[example['bearer']]}"
        body = json.loads(_fill(example["body"], values)) if example["body"] else None
        if body and body.get("connector_type") == "postgresql":
            body = {**body, "connector_type": "sqlite", "config": {"file_path": str(source)}}
        response = api.request(example["method"], url, headers=headers, json=body)
        assert response.status_code < 400, f"{example['method']} {example['url']}: {response.status_code} {response.text}"
        answer = response.json() if "json" in response.headers.get("content-type", "") else response.text
        if example["capture"]:
            values[example["capture"]] = str(_pick(answer, example["jq"]))
        answers.append((example, answer))

    by_url = {example["url"].split("?")[0]: answer for example, answer in answers}
    assert by_url["/api/v1/projects/$PROJECT/extraction/connections/$CONNECTION/test"]["success"] is True
    preview = by_url["/api/v1/projects/$PROJECT/datasets/$DATASET/preview"]
    assert len(preview["rows"]) == 4
    run = by_url["/api/v1/projects/$PROJECT/runs/$RUN"]
    assert run["status"] == "succeeded"
    download = by_url["/api/v1/projects/$PROJECT/datasets/$DATASET/download"]
    assert download.splitlines()[0] == "id,customer,amount"
    assert len(download.strip().splitlines()) == 5
