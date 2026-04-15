from fastapi.testclient import TestClient

from api_gateway.dependencies import get_db
from api_gateway.main import app

client = TestClient(app)


def override_db():
    yield object()


def test_projects_route_requires_authentication() -> None:
    app.dependency_overrides[get_db] = override_db
    try:
        response = client.get("/api/v1/projects")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
