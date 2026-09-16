from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from service_ingestion.schemas import IngestionUpload
from shared_python.errors import BadRequestError
from shared_python.storage.base import sanitize_filename

# A content type that contradicts the extension is worth refusing early -- but
# only where the pairing is genuinely wrong. Browsers, mail gateways and `curl`
# all send `application/octet-stream` for anything they do not recognise, and
# refusing that would refuse most real uploads. The sniffer reads the bytes
# either way and overrules both.
_ALLOWED_MIME_HINTS = {
    'csv': {'text/csv', 'application/csv', 'text/plain'},
    'xlsx': {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/octet-stream',
    },
    'json': {'application/json', 'text/json', 'text/plain'},
}


def infer_extension(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower().lstrip('.')
    return suffix


async def read_upload_file(upload_file: UploadFile) -> IngestionUpload:
    if not upload_file.filename:
        raise BadRequestError('Uploaded file must include a file name.')
    return IngestionUpload(
        file_name=upload_file.filename,
        content_type=upload_file.content_type or '',
        file_bytes=await upload_file.read(),
    )


def validate_upload_file(upload_file: IngestionUpload, settings) -> str:
    extension = infer_extension(upload_file.file_name)
    if extension not in settings.allowed_upload_extensions:
        allowed = ', '.join(sorted(settings.allowed_upload_extensions))
        raise BadRequestError(
            f"'{extension or 'no extension'}' is not a file type this deployment accepts. "
            f'Allowed: {allowed}.'
        )

    content_type = (upload_file.content_type or '').lower()
    allowed_mimes = _ALLOWED_MIME_HINTS.get(extension, set())
    if content_type and allowed_mimes and content_type not in allowed_mimes:
        if extension == 'csv' and content_type.startswith('text/'):
            return extension
        raise BadRequestError('Uploaded file content type does not match the file extension.')

    return extension


def build_upload_path(*, project_id: str, dataset_id: str, original_filename: str) -> tuple[str, str]:
    safe_name = sanitize_filename(original_filename)
    relative_path = f'uploads/{project_id}/{dataset_id}/{uuid4().hex}_{safe_name}'
    return relative_path, safe_name


def build_derived_dataset_path(*, project_id: str, dataset_id: str, basename: str = 'transformed.csv') -> tuple[str, str]:
    """Relative storage path for a derived (transformed) dataset artifact. Output is CSV."""
    safe_name = sanitize_filename(basename)
    if not safe_name.lower().endswith('.csv'):
        safe_name = f'{safe_name}.csv'
    relative_path = f'derived/{project_id}/{dataset_id}/{uuid4().hex}_{safe_name}'
    return relative_path, safe_name
