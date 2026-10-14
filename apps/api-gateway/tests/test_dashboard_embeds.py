"""Dashboards shown on other sites, by signed links (adoption-readiness A8, Y4).

Through HTTP, as a partner would: make an embed, open its link without
signing in, sign links of our own with its secret (short, and with a filter
that shows one region), and check that a link cannot be altered, stretched,
signed with another secret or with no algorithm, and that turning the embed
off stops every link at once.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
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
from pipewright import embed_link, embed_token
from service_governance.audit_words import summarise
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"


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
    monkeypatch.setattr(dependencies, "storage_backend", LocalStorageBackend(str(tmp_path / "storage")))
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    monkeypatch.setenv("WEB_BASE_URL", "https://pipewright.example.com")
    db = factory()
    db.add(User(username="owner", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
    db.commit()
    db.close()
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json()


def _sales_dashboard(api) -> tuple[str, str]:
    project = _ok(api.post("/api/v1/projects", json={"name": "Shop"}), 201)["id"]
    dataset = _ok(api.post(f"/api/v1/projects/{project}/samples/orders"), 201)["dataset"]["id"]
    metric = _ok(api.post(f"/api/v1/projects/{project}/metrics", json={
        "name": "Revenue", "dataset_id": dataset, "aggregation": "sum", "column": "amount",
    }), 201)["id"]
    chart = _ok(api.post(f"/api/v1/projects/{project}/charts", json={
        "name": "Revenue by region", "dataset_id": dataset, "chart_type": "bar", "metric_id": metric,
        "query": {"dimensions": ["region"]},
    }), 201)["id"]
    dashboard = _ok(api.post(f"/api/v1/projects/{project}/dashboards", json={
        "name": "Sales", "tiles": [{"kind": "chart", "chart_id": chart}],
    }), 201)["id"]
    return project, dashboard


def _public(path: str):
    return TestClient(app).get(f"/api/v1/public/embeds/{path}")


def _labels(view) -> set[str]:
    return set(view["tiles"][0]["data"]["labels"])


def test_an_embed_link_shows_the_dashboard_to_someone_not_signed_in(api) -> None:
    project, dashboard = _sales_dashboard(api)
    made = _ok(api.post(f"/api/v1/projects/{project}/dashboards/{dashboard}/embeds", json={
        "name": "Customer portal", "days": 30,
    }), 201)
    assert made["state"] == "on" and made["signing_secret"].startswith("emb_")
    assert made["url"] == f"https://pipewright.example.com/embed/{made['token']}"
    expires = datetime.fromisoformat(made["expires_at"].replace("Z", "+00:00"))
    expires = expires if expires.tzinfo else expires.replace(tzinfo=UTC)
    assert timedelta(days=29) < expires - datetime.now(UTC) <= timedelta(days=30)

    view = _ok(_public(made["token"]))
    assert view["name"] == "Sales"
    assert {"North", "South", "East", "West"} <= _labels(view)
    assert dashboard not in json.dumps(view) and project not in json.dumps(view), "no ids reach the viewer"

    [listed] = _ok(api.get(f"/api/v1/projects/{project}/dashboards/{dashboard}/embeds"))["items"]
    assert listed["signing_secret"] is None, "the secret is shown once, when it is made"
    assert listed["secret_hint"] == f"emb_…{made['signing_secret'][-4:]}"
    assert listed["token"] == made["token"] and listed["last_opened_at"] is not None


def test_a_partner_signs_short_links_that_show_one_customers_rows(api) -> None:
    project, dashboard = _sales_dashboard(api)
    made = _ok(api.post(f"/api/v1/projects/{project}/dashboards/{dashboard}/embeds", json={"name": "Portal"}), 201)
    secret, embed = made["signing_secret"], made["id"]
    soon = datetime.now(UTC) + timedelta(minutes=10)

    north = jwt.encode({"embed": embed, "exp": soon, "filters": [{"column": "region", "value": "North"}]},
                       secret, algorithm="HS256")
    assert _labels(_ok(_public(north))) == {"North"}
    # The Python client signs the same links, with nothing but the standard library.
    south = embed_token(embed, secret, minutes=5, filters=[{"column": "region", "value": "South"}])
    assert _labels(_ok(_public(south))) == {"South"}
    assert embed_link("https://pw.example.com/", embed, secret).startswith("https://pw.example.com/embed/ey")

    # The viewer cannot widen the filter: change it and the signature no longer matches.
    head, body, signature = north.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=="))
    claims["filters"] = []
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    assert _public(f"{head}.{forged}.{signature}").status_code == 404

    assert _public(jwt.encode({"embed": embed, "exp": soon}, "emb_" + "not-the-secret" * 4, algorithm="HS256")).status_code == 404
    unsigned = jwt.encode({"embed": embed, "exp": soon}, None, algorithm="none")
    assert _public(unsigned).status_code == 404, "a token cannot choose to be unsigned"
    assert _public(jwt.encode({"embed": embed}, secret, algorithm="HS256")).status_code == 404, "an expiry is required"
    assert _public("not-a-token").status_code == 404

    ran_out = _public(jwt.encode({"embed": embed, "exp": datetime.now(UTC) - timedelta(minutes=5)}, secret, algorithm="HS256"))
    assert ran_out.status_code == 410 and "run out" in ran_out.json()["detail"]

    # A filter on a column a chart's data lacks fails closed: that chart shows nothing.
    elsewhere = jwt.encode({"embed": embed, "exp": soon, "filters": [{"column": "tenant", "value": "A"}]},
                           secret, algorithm="HS256")
    tile = _ok(_public(elsewhere))["tiles"][0]
    assert tile["data"]["labels"] == [] and tile["data"]["warnings"] == ["This chart could not be loaded."]

    odd = jwt.encode({"embed": embed, "exp": soon, "filters": [{"column": "region", "operator": "like", "value": "N"}]},
                     secret, algorithm="HS256")
    assert _public(odd).status_code == 400 and "like" in _public(odd).json()["detail"]


def test_turning_an_embed_off_stops_every_link_signed_with_it(api) -> None:
    project, dashboard = _sales_dashboard(api)
    made = _ok(api.post(f"/api/v1/projects/{project}/dashboards/{dashboard}/embeds", json={"name": "Portal"}), 201)
    own = jwt.encode({"embed": made["id"], "exp": datetime.now(UTC) + timedelta(minutes=10)},
                     made["signing_secret"], algorithm="HS256")
    assert _public(made["token"]).status_code == 200 and _public(own).status_code == 200

    off = _ok(api.delete(f"/api/v1/projects/{project}/dashboards/{dashboard}/embeds/{made['id']}"))
    assert off["state"] == "off" and off["token"] is None and off["url"] is None
    assert _public(made["token"]).status_code == 404
    assert _public(own).status_code == 404

    refused = api.post(f"/api/v1/projects/{project}/dashboards/{dashboard}/embeds", json={"name": "Portal", "days": 1000})
    assert refused.status_code == 400 and "365" in refused.json()["detail"]


def test_the_audit_log_says_what_happened_to_an_embed() -> None:
    base = "/api/v1/projects/3f1d2c3b-0000-4000-8000-000000000001/dashboards/3f1d2c3b-0000-4000-8000-000000000002"
    assert summarise("POST", f"{base}/embeds") == "made a link to show a dashboard on another site"
    assert summarise("DELETE", f"{base}/embeds/3f1d2c3b-0000-4000-8000-000000000003") == (
        "turned off a dashboard shown on another site"
    )


def test_the_guides_signing_code_works_as_written(api) -> None:
    """docs/user/api.md gives a partner a function to sign links; run that exact code."""
    import re
    from pathlib import Path

    guide = (Path(__file__).resolve().parents[3] / "docs" / "user" / "api.md").read_text()
    section = guide.split("## Embedding a dashboard", 1)[1].split("\n## ", 1)[0]
    [code] = re.findall(r"```python\n(.*?)```", section, flags=re.S)
    namespace: dict = {}
    exec(compile(code, "api.md", "exec"), namespace)  # noqa: S102 - the guide's own code

    project, dashboard = _sales_dashboard(api)
    made = _ok(api.post(f"/api/v1/projects/{project}/dashboards/{dashboard}/embeds", json={"name": "Portal"}), 201)
    src = namespace["embed_src"]("https://pw.example.com", made["id"], made["signing_secret"], "C107")
    token = src.removeprefix("https://pw.example.com/embed/")
    assert _labels(_ok(_public(token))) == {"North", "East", "West"}, "the regions customer C107 ordered in"
