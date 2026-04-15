import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from service_ingestion.contracts import build_derived_dataset_path, build_upload_path, read_upload_file, validate_upload_file
from shared_python.errors import BadRequestError


class UploadStub:
    def __init__(self, file_name: str, content_type: str):
        self.file_name = file_name
        self.content_type = content_type


def test_validate_upload_file_rejects_unsupported_extensions() -> None:
    with pytest.raises(BadRequestError):
        validate_upload_file(
            UploadStub("bad.txt", "text/plain"),
            SimpleNamespace(allowed_upload_extensions=["csv", "xlsx", "json"]),
        )


def test_read_upload_file_reads_fastapi_uploads() -> None:
    upload = UploadFile(filename="orders.csv", file=BytesIO(b"name,amount\nalpha,10\n"), headers={"content-type": "text/csv"})
    payload = asyncio.run(read_upload_file(upload))
    assert payload.file_name == "orders.csv"
    assert payload.file_bytes.startswith(b"name,amount")


def test_build_upload_path_sanitizes_filename() -> None:
    relative_path, safe_name = build_upload_path(
        project_id="project-1",
        dataset_id="dataset-1",
        original_filename="../../weird report.csv",
    )
    assert relative_path.startswith("uploads/project-1/dataset-1/")
    assert ".." not in relative_path
    assert safe_name.endswith("report.csv")


def test_build_derived_dataset_path_uses_derived_prefix() -> None:
    relative_path, safe_name = build_derived_dataset_path(
        project_id="project-1",
        dataset_id="dataset-1",
        basename="output.csv",
    )
    assert relative_path.startswith("derived/project-1/dataset-1/")
    assert safe_name.endswith(".csv")
