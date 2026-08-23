from __future__ import annotations

from service_quality.drift import detect_schema_drift


def schema(*columns: tuple[str, str]) -> dict:
    return {
        "columns": [{"name": name, "inferred_type": inferred} for name, inferred in columns],
        "ordered_columns": [name for name, _ in columns],
    }


def test_identical_schemas_report_no_drift() -> None:
    current = schema(("id", "int"), ("name", "string"))
    report = detect_schema_drift(current, current)
    assert report.has_drift is False
    assert report.severity == "none"
    assert report.summary == "Schema is unchanged."


def test_added_column_is_compatible() -> None:
    report = detect_schema_drift(
        schema(("id", "int")), schema(("id", "int"), ("email", "string"))
    )
    assert report.severity == "compatible"
    assert report.added_columns == ["email"]
    assert report.removed_columns == []


def test_removed_column_is_breaking() -> None:
    report = detect_schema_drift(
        schema(("id", "int"), ("email", "string")), schema(("id", "int"))
    )
    assert report.severity == "breaking"
    assert report.removed_columns == ["email"]


def test_widening_type_change_is_risky() -> None:
    report = detect_schema_drift(schema(("amount", "int")), schema(("amount", "float")))
    assert report.severity == "risky"
    assert report.type_changes[0].previous_type == "int"
    assert report.type_changes[0].current_type == "float"


def test_incompatible_type_change_is_breaking() -> None:
    report = detect_schema_drift(schema(("amount", "string")), schema(("amount", "int")))
    assert report.severity == "breaking"
    assert report.type_changes[0].severity == "breaking"


def test_breaking_outranks_compatible() -> None:
    """A single removal makes the whole change breaking even alongside additions."""
    report = detect_schema_drift(
        schema(("id", "int"), ("old", "string")), schema(("id", "int"), ("new", "string"))
    )
    assert report.severity == "breaking"
    assert report.added_columns == ["new"]
    assert report.removed_columns == ["old"]


def test_reordering_is_detected() -> None:
    report = detect_schema_drift(
        schema(("a", "int"), ("b", "string")), schema(("b", "string"), ("a", "int"))
    )
    assert report.reordered is True
    assert report.severity == "none"
    assert report.has_drift is False


def test_missing_previous_schema_is_not_drift() -> None:
    report = detect_schema_drift(None, schema(("id", "int")))
    assert report.has_drift is False
    assert "No previous schema" in report.summary


def test_plain_mapping_schema_is_supported() -> None:
    """Schemas stored as {column: type} compare the same as the profiling shape."""
    report = detect_schema_drift({"id": "int"}, {"id": "int", "extra": "string"})
    assert report.added_columns == ["extra"]
    assert report.severity == "compatible"


def test_summary_counts_each_kind_of_change() -> None:
    report = detect_schema_drift(
        schema(("id", "int"), ("drop_me", "string"), ("amount", "int")),
        schema(("id", "int"), ("amount", "float"), ("added", "string")),
    )
    assert "1 column(s) added" in report.summary
    assert "1 column(s) removed" in report.summary
    assert "1 type change(s)" in report.summary


def test_report_serialises_for_storage() -> None:
    report = detect_schema_drift(schema(("amount", "int")), schema(("amount", "float")))
    payload = report.to_dict()
    assert payload["severity"] == "risky"
    assert payload["type_changes"][0]["column"] == "amount"
    assert payload["has_drift"] is True
