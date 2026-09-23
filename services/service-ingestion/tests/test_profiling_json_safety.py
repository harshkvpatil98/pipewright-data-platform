"""Previews and profiles must be JSON, whatever a driver hands back.

Found live: a PostgreSQL extraction from a table with a uuid primary key read
its rows fine and then failed the whole run when the dataset's preview and
profile were written, because a UUID object reached the JSON column untouched.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from ipaddress import ip_address

import pandas as pd

from service_ingestion.profiling import build_preview, build_profile


def test_driver_types_are_rendered_as_json_safe_values():
    frame = pd.DataFrame(
        {
            "id": [uuid.UUID("11111111-2222-4333-8444-555555555555"), uuid.uuid4()],
            "amount": [Decimal("1.50"), Decimal("2.25")],
            "seen": [date(2026, 9, 23), None],
            "addr": [ip_address("10.0.0.1"), None],
            "blob": [b"\x00\x01", None],
        }
    )
    preview = build_preview(dataframe=frame, limit=5)
    profile = build_profile(dataframe=frame, sample_limit=3, file_size_bytes=10)

    import json

    json.dumps(preview)  # must not raise
    json.dumps(profile)
    first = preview["rows"][0]
    assert first["id"] == "11111111-2222-4333-8444-555555555555"
    assert first["amount"] == 1.5 and first["seen"] == "2026-09-23"
    assert first["addr"] == "10.0.0.1" and first["blob"] == "<2 bytes>"
    id_profile = next(column for column in profile["columns"] if column["name"] == "id")
    assert all(isinstance(sample, str) for sample in id_profile["sample_values"])
