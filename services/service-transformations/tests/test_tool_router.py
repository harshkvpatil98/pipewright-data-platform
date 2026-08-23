"""The tool catalogue and preview endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_transformations.router import build_router
from shared_python.errors import register_exception_handlers


def client() -> TestClient:
    user = UserRead(
        id=uuid.uuid4(), username="analyst", role="admin", is_active=True,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(lambda: None, lambda: user))
    return TestClient(app)


class TestCatalogue:
    def test_it_returns_every_tool_with_its_categories(self) -> None:
        response = client().get("/transformations/tools")
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) > 150
        assert "Text" in body["categories"]
        first = body["items"][0]
        assert {"name", "title", "category", "summary", "params", "example"} <= set(first)

    def test_it_can_be_searched_by_a_word_people_use(self) -> None:
        body = client().get("/transformations/tools", params={"query": "zip code"}).json()
        assert body["items"][0]["name"] == "clean.postal_code"

    def test_it_can_be_filtered_to_a_category(self) -> None:
        body = client().get("/transformations/tools", params={"category": "Numeric"}).json()
        assert body["items"]
        assert {item["category"] for item in body["items"]} == {"Numeric"}

    def test_it_offers_date_tools_on_a_date_and_not_on_a_number(self) -> None:
        dates = client().get("/transformations/tools", params={"column_type": "timestamp"}).json()
        numbers = client().get("/transformations/tools", params={"column_type": "float64"}).json()
        assert "date.year" in {item["name"] for item in dates["items"]}
        assert "date.year" not in {item["name"] for item in numbers["items"]}
        assert "numeric.round" in {item["name"] for item in numbers["items"]}

    def test_an_unknown_type_says_so_rather_than_returning_everything(self) -> None:
        response = client().get("/transformations/tools", params={"column_type": "wibble"})
        assert response.status_code == 400
        assert "wibble" in response.json()["detail"]

    def test_every_parameter_carries_enough_to_build_a_form(self) -> None:
        body = client().get("/transformations/tools", params={"query": "pad left"}).json()
        param = body["items"][0]["params"][0]
        assert param["label"] and param["kind"] and "required" in param


class TestPreview:
    def test_it_shows_what_a_tool_would_do(self) -> None:
        response = client().post(
            "/transformations/tools/preview",
            json={
                "tool": "text.trim",
                "column": "name",
                "rows": [{"name": "  Ada  "}, {"name": None}],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rows"] == [{"name": "Ada"}, {"name": None}]

    def test_it_can_write_into_a_new_column(self) -> None:
        body = client().post(
            "/transformations/tools/preview",
            json={
                "tool": "text.upper", "column": "name", "into": "shouty",
                "rows": [{"name": "ada"}],
            },
        ).json()
        assert body["columns"] == ["name", "shouty"]
        assert body["rows"] == [{"name": "ada", "shouty": "ADA"}]

    def test_a_timestamp_survives_the_json_round_trip(self) -> None:
        # A Timestamp in a DataFrame is not JSON-serialisable, and a 500 from a
        # preview is the worst possible place to discover that.
        body = client().post(
            "/transformations/tools/preview",
            json={
                "tool": "date.start_of_period", "column": "when",
                "params": {"period": "month"},
                "rows": [{"when": "2026-08-23"}],
            },
        ).json()
        assert body["rows"][0]["when"].startswith("2026-08-01")

    def test_a_bad_pattern_is_a_message_not_a_crash(self) -> None:
        response = client().post(
            "/transformations/tools/preview",
            json={
                "tool": "text.regex_extract", "column": "a",
                "params": {"pattern": "([unclosed"},
                "rows": [{"a": "x"}],
            },
        )
        assert response.status_code == 400
        assert "will not compile" in response.json()["detail"]

    def test_an_unknown_tool_is_refused(self) -> None:
        response = client().post(
            "/transformations/tools/preview",
            json={"tool": "text.nope", "column": "a", "rows": [{"a": "x"}]},
        )
        assert response.status_code == 400

    def test_no_rows_is_not_an_error(self) -> None:
        response = client().post(
            "/transformations/tools/preview",
            json={"tool": "text.trim", "column": "a", "rows": []},
        )
        # Nothing to show, but nothing wrong either: the settings panel asks for
        # a preview before any rows have loaded.
        assert response.status_code == 400
        assert "not in this dataset" in response.json()["detail"].lower()

    def test_the_warning_names_values_it_could_not_read(self) -> None:
        body = client().post(
            "/transformations/tools/preview",
            json={
                "tool": "type.to_number", "column": "a",
                "rows": [{"a": "1"}, {"a": "x"}, {"a": "2"}],
            },
        ).json()
        assert body["warnings"]
        assert "1 of 3" in body["warnings"][0]


class TestGeneratedReference:
    """`docs/transformation-tools.md` is generated; a stale copy is a lie."""

    def test_the_checked_in_reference_matches_the_registry(self) -> None:
        from pathlib import Path

        from service_transformations.tools.docs import as_markdown

        # Walk up to the repository root from this test file.
        root = Path(__file__).resolve().parents[3]
        reference = root / "docs" / "transformation-tools.md"
        assert reference.exists(), "the generated tool reference is missing"
        assert reference.read_text() == as_markdown(), (
            "docs/transformation-tools.md is out of date. Regenerate it with:\n"
            "  python -c \"from service_transformations.tools.docs import as_markdown;"
            " open('docs/transformation-tools.md','w').write(as_markdown())\""
        )

    def test_every_tool_appears_in_it(self) -> None:
        import service_transformations.tools as tools
        from service_transformations.tools.docs import as_markdown

        text = as_markdown()
        missing = [name for name in tools.TOOLS if f"`{name}`" not in text]
        assert missing == []
