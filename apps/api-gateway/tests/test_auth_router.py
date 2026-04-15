from unittest.mock import patch

from fastapi.testclient import TestClient

from api_gateway.main import app

client = TestClient(app)


@patch("service_auth.router.authenticate_user")
@patch("service_auth.router.create_access_token")
def test_login_returns_bearer_token(create_access_token, authenticate_user) -> None:
    authenticate_user.return_value = type(
        "User",
        (),
        {
            "id": "1c1bb0a6-a6b0-4aa1-aed2-5df11f0c8238",
            "username": "platform-admin",
            "role": "admin",
            "is_active": True,
            "created_at": "2026-04-02T00:00:00+00:00",
            "updated_at": "2026-04-02T00:00:00+00:00",
        },
    )()
    create_access_token.return_value = ("signed-token", 3600)

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "platform-admin", "password": "super-secret-password"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "signed-token"
