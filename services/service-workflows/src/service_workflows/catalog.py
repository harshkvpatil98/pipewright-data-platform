"""Macro reference, served to the UI so the editor documents itself."""

from __future__ import annotations

from service_workflows.schemas import MacroCatalogResponse, MacroReference

_MACROS: tuple[tuple[str, str, str | None], ...] = (
    ("{{ ds }}", "The run's date, as YYYY-MM-DD.", "orders_{{ ds }}"),
    ("{{ run_date }}", "Same as ds.", None),
    ("{{ yesterday }}", "The day before the run's date.", None),
    ("{{ tomorrow }}", "The day after the run's date.", None),
    ("{{ ds_nodash }}", "The run's date without dashes.", "orders_{{ ds_nodash }}"),
    ("{{ ds_sub(n) }}", "n days before the run's date.", "since '{{ ds_sub(7) }}'"),
    ("{{ ds_add(n) }}", "n days after the run's date.", None),
    ("{{ year }}", "Four-digit year of the run's date.", "s3://bucket/{{ year }}/{{ month }}"),
    ("{{ month }}", "Two-digit month.", None),
    ("{{ day }}", "Two-digit day.", None),
    ("{{ hour }}", "Two-digit hour, for hourly schedules.", None),
    ("{{ month_start }}", "First day of the run's month.", None),
    ("{{ run_ts }}", "The run's date and time in ISO format.", None),
    ("{{ executed_at }}", "When the run actually started, which differs on a backfill.", None),
    ("{{ workflow_name }}", "This workflow's name.", None),
    ("{{ params.name }}", "A value from the run's parameters.", "{{ params.region }}"),
)


def macro_catalog() -> MacroCatalogResponse:
    return MacroCatalogResponse(
        items=[
            MacroReference(token=token, description=description, example=example)
            for token, description, example in _MACROS
        ]
    )
