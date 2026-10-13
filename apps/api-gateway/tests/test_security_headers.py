"""Every answer from the API carries the browser security headers (A6, W7)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_gateway.main import app

client = TestClient(app)


def test_answers_carry_the_security_headers() -> None:
    for path in ("/api/v1/health/live", "/docs", "/api/v1/no-such-page"):
        response = client.get(path)
        assert response.headers["x-content-type-options"] == "nosniff", path
        assert response.headers["x-frame-options"] == "DENY", path
        assert response.headers["referrer-policy"] == "no-referrer", path
