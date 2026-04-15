import pytest
from pydantic import ValidationError

from service_sources.schemas import SourceCreate


def test_source_schema_accepts_supported_source_types() -> None:
    payload = SourceCreate(name="Warehouse feed", source_type="postgres", config_json={"table": "orders"})
    assert payload.source_type == "postgres"


def test_source_schema_rejects_unknown_source_types() -> None:
    with pytest.raises(ValidationError):
        SourceCreate(name="Unknown feed", source_type="ftp", config_json={})
