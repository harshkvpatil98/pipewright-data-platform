"""Running a conversion's recipes here, in order, on frames given for what they read (E2, X3)."""

from __future__ import annotations

import io
import re
import sqlite3
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from api_gateway.conversions.model import Conversion
from service_ingestion.read_copy import parse as parse_file
from service_transformations.executor import apply_transformation_steps
from service_transformations.parameters import resolve
from service_transformations.steps.context import StepContext


def run_recipes(conversion: Conversion, frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Every complete recipe's result, by key, with seeds read as the platform reads a file."""
    frames = {**frames, **{seed.key: parse_file(seed.data, file_type="csv", spec=None) for seed in conversion.seeds}}
    ids: dict[str, str] = {}

    def resolved(value: Any) -> Any:
        if isinstance(value, dict) and "$dataset" in value:
            return ids.setdefault(value["$dataset"], str(uuid.uuid4()))
        if isinstance(value, dict):
            return {key: resolved(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolved(item) for item in value]
        return value

    pending = [recipe for recipe in conversion.recipes if recipe.complete]
    while pending:
        progressed = False
        for recipe in list(pending):
            steps = resolved(recipe.steps)
            needed = [key for key, identifier in ids.items() if identifier in str(steps)]
            if recipe.reads not in frames or any(key not in frames for key in needed):
                continue
            by_id = {identifier: frames[key] for key, identifier in ids.items() if key in frames}
            context = StepContext(resolve_dataset=lambda i, by_id=by_id: by_id[i].copy(), describe_dataset=str)
            frames[recipe.key] = apply_transformation_steps(frames[recipe.reads].copy(),
                                                            resolve(steps, recipe.parameters), context)[0]
            pending.remove(recipe)
            progressed = True
        if not progressed:
            raise AssertionError(f"These recipes read what is not here: {[r.key for r in pending]}")
    return frames


def rows(frame: pd.DataFrame) -> list[tuple]:
    """A frame's rows in order, each value as plain Python."""
    def value(v):
        if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)):
            return None
        if isinstance(v, bool) or hasattr(v, "dtype") and str(getattr(v, "dtype", "")) == "bool":
            return bool(v)
        if isinstance(v, (int, float)) or hasattr(v, "item"):
            number = float(v)
            return int(number) if number.is_integer() else round(number, 9)
        return str(v)

    return [tuple(value(v) for v in row) for row in frame.itertuples(index=False)]


def entries(conversion: Conversion) -> dict[str, Any]:
    return {entry.subject: entry for section in conversion.sections for entry in section.entries}


# The dbt fixture, shared by the importer's tests and the API's.
DBT_FIXTURE = Path(__file__).parent / "fixtures" / "conversions" / "dbt_shop"
SEGMENTS = pd.DataFrame({"customer_id": [1, 2, 3, 4], "segment": ["gold", "silver", "gold", "bronze"]})


def dbt_project_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(DBT_FIXTURE.rglob("*")):
            if path.is_file():
                archive.write(path, f"shop/{path.relative_to(DBT_FIXTURE)}")
    return buffer.getvalue()


def dbt_sqlite_model(name: str) -> pd.DataFrame:
    """The model as dbt would build it, in SQLite: its SQL with the Jinja written in by hand."""
    connection = sqlite3.connect(":memory:")
    for path in (DBT_FIXTURE / "seeds").glob("*.csv"):
        parse_file(path.read_bytes(), file_type="csv", spec=None).to_sql(path.stem, connection, index=False)
    SEGMENTS.to_sql("crm_segments", connection, index=False)

    def compiled(model: str) -> str:
        text = next((DBT_FIXTURE / "models").rglob(f"{model}.sql")).read_text()
        text = re.sub(r"\{\{\s*config\(.*?\)\s*\}\}", "", text, flags=re.S)
        text = re.sub(r"\{%\s*if is_incremental\(\)\s*%\}.*?\{%\s*endif\s*%\}", "", text, flags=re.S)
        text = re.sub(r"\{\{\s*ref\('(\w+)'\)\s*\}\}", r"\1", text)
        text = text.replace("{{ source('crm', 'segments') }}", "crm_segments")
        return text.replace("{{ var('min_order_amount') }}", "15")

    for model in ("stg_customers", "stg_orders", "stg_payments", "orders", "customers", "big_orders"):
        connection.execute(f"CREATE VIEW {model} AS {compiled(model)}")
    return pd.read_sql(f"SELECT * FROM {name}", connection)


def sorted_rows(frame: pd.DataFrame) -> list[tuple]:
    def value(v):
        if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)):
            return None
        return round(float(v), 9) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)

    return sorted((tuple(value(v) for v in row) for row in frame.itertuples(index=False)), key=repr)
