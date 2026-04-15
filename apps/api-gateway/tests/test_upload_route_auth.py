from io import BytesIO

from fastapi.testclient import TestClient

from api_gateway.dependencies import get_db
from api_gateway.main import app

client = TestClient(app)


def override_db():
    yield object()


def test_upload_route_requires_authentication() -> None:
    app.dependency_overrides[get_db] = override_db
    try:
        response = client.post(
            "/api/v1/projects/11111111-1111-1111-1111-111111111111/datasets/upload",
            files={"file": ("orders.csv", BytesIO(b"name,amount\nalpha,10\n"), "text/csv")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
