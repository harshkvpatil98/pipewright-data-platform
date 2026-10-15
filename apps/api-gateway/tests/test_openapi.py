"""The API reference must build.

`/docs` and `/redoc` both render from `/openapi.json`, and FastAPI builds that
document for every route at once: one unresolvable annotation anywhere fails
the whole reference with a 500. That happened (a function-local `Response`
import under postponed annotations) and nothing noticed, because no test asked
for the schema.
"""

from fastapi.testclient import TestClient

from api_gateway.main import app


def test_openapi_document_builds_for_every_route() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200, response.text[:500]
    document = response.json()
    assert document["paths"], "the reference lists no operations"
    # A broken schema tends to fail partially as well as wholly; spot-check
    # routes from several services so a missing router is visible.
    paths = document["paths"]
    for expected in ("/api/v1/audits/export", "/api/v1/projects", "/api/v1/auth/login"):
        assert expected in paths, f"{expected} missing from the reference"


def test_interactive_reference_pages_load() -> None:
    client = TestClient(app)
    for page in ("/api/docs", "/api/redoc"):
        response = client.get(page)
        assert response.status_code == 200, page
    # The old addresses still lead there, for anyone with a bookmark.
    for old, new in (("/docs", "/api/docs"), ("/redoc", "/api/redoc")):
        moved = client.get(old, follow_redirects=False)
        assert (moved.status_code, moved.headers["location"]) == (308, new)
