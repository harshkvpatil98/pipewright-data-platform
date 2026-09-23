from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile, status

from service_auth.schemas import UserRead
from shared_python.errors import BadRequestError

from service_ingestion import analysis_service, resumable
from service_ingestion.contracts import read_upload_file
from service_ingestion.schemas import (
    AnalyseResponse,
    DatasetUploadResponse,
    IngestSpecListResponse,
    IngestSpecRead,
    RememberSpecRequest,
    UploadSessionRead,
)
from service_ingestion.service import ingest_project_file


def build_router(
    get_db: Callable,
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable,
    settings,
) -> APIRouter:
    router = APIRouter(tags=['ingestion'])

    @router.post(
        '/projects/{project_id}/datasets/upload',
        response_model=DatasetUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_dataset(
        project_id: uuid.UUID,
        dataset_name: str | None = Query(default=None),
        spec_id: uuid.UUID | None = Query(
            default=None,
            description='A saved ingest spec to read this file with, rather than inferring.',
        ),
        file: UploadFile = File(...),
        ingest_spec: str | None = Form(
            default=None,
            description=(
                'The reviewed spec, as JSON. Sent by the upload screen after somebody has '
                'looked at what the file turned out to be and corrected anything wrong. '
                'Wins over both inference and a saved spec, because it is the most '
                'recent human decision.'
            ),
        ),
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend = Depends(get_storage_backend),
    ) -> DatasetUploadResponse:
        try:
            upload = await read_upload_file(file)
            spec, record = _resolve_spec(
                db,
                project_id=project_id,
                spec_id=spec_id,
                file_name=upload.file_name,
                current_user=current_user,
            )
            reviewed = _parse_inline_spec(ingest_spec)
            if reviewed is not None:
                spec, record = reviewed, None
            response = ingest_project_file(
                db,
                project_id=project_id,
                dataset_name=dataset_name,
                upload_file=upload,
                storage_backend=storage_backend,
                settings=settings,
                current_user=current_user,
                ingest_spec=spec,
            )
            if record is not None:
                analysis_service.record_use(db, record)
                db.commit()
            return response
        finally:
            await file.close()

    # ----------------------------------------------------- analyse first

    @router.post('/projects/{project_id}/datasets/analyze', response_model=AnalyseResponse)
    async def analyze_dataset(
        project_id: uuid.UUID,
        spec_id: uuid.UUID | None = Query(default=None),
        file: UploadFile = File(...),
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> AnalyseResponse:
        """Work out how to read a file, and store nothing.

        This is the "preview before commit" half of ingestion: every inferred
        decision comes back with its confidence and evidence, the questions the
        file cannot answer come back as `questions`, and the caller sends the
        corrected spec to `upload` when it is happy.
        """
        try:
            upload = await read_upload_file(file)
            if len(upload.file_bytes) > settings.max_upload_size_bytes:
                raise BadRequestError('Uploaded file exceeds the configured maximum size.')
            return AnalyseResponse(
                **analysis_service.analyse_upload(
                    db,
                    project_id=project_id,
                    file_name=upload.file_name,
                    content_type=upload.content_type,
                    payload=upload.file_bytes,
                    current_user=current_user,
                    spec_id=spec_id,
                )
            )
        finally:
            await file.close()

    # ------------------------------------------------------ saved specs

    @router.get('/projects/{project_id}/ingest-specs', response_model=IngestSpecListResponse)
    def list_specs(
        project_id: uuid.UUID,
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> IngestSpecListResponse:
        return IngestSpecListResponse(
            items=[
                IngestSpecRead(**row)
                for row in analysis_service.list_specs(
                    db, project_id=project_id, current_user=current_user
                )
            ]
        )

    @router.post(
        '/projects/{project_id}/ingest-specs',
        response_model=IngestSpecRead,
        status_code=status.HTTP_201_CREATED,
    )
    def remember_spec(
        project_id: uuid.UUID,
        payload: RememberSpecRequest,
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> IngestSpecRead:
        """Save a confirmed spec so the next file of this kind reuses it."""
        record = analysis_service.remember(
            db,
            project_id=project_id,
            label=payload.label,
            file_name=payload.file_name,
            payload_spec=payload.spec,
            columns=payload.columns,
            current_user=current_user,
        )
        db.commit()
        return IngestSpecRead(**analysis_service._render(record))

    @router.delete(
        '/projects/{project_id}/ingest-specs/{spec_id}',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_spec(
        project_id: uuid.UUID,
        spec_id: uuid.UUID,
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        analysis_service.delete_spec(
            db, project_id=project_id, spec_id=spec_id, current_user=current_user
        )
        db.commit()

    # ------------------------------------------- resumable large uploads

    @router.post(
        '/projects/{project_id}/datasets/uploads',
        response_model=UploadSessionRead,
        status_code=status.HTTP_201_CREATED,
    )
    def start_upload(
        project_id: uuid.UUID,
        file_name: str = Body(..., embed=True),
        total_bytes: int = Body(..., embed=True),
        content_type: str = Body(default='', embed=True),
        sha256: str | None = Body(default=None, embed=True),
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> UploadSessionRead:
        """Begin a chunked upload, for a file too large to send in one request."""
        from service_projects.contracts import ensure_owned_project

        ensure_owned_project(db, project_id, current_user.id)
        if total_bytes > settings.max_upload_size_bytes:
            raise BadRequestError('Uploaded file exceeds the configured maximum size.')
        session = resumable.SESSIONS.create(
            db,
            project_id=project_id,
            file_name=file_name,
            content_type=content_type,
            total_bytes=total_bytes,
            expected_sha256=sha256,
            created_by_user_id=current_user.id,
        )
        return UploadSessionRead(**session.to_dict())

    @router.get(
        '/projects/{project_id}/datasets/uploads/{upload_id}',
        response_model=UploadSessionRead,
    )
    def upload_status(
        project_id: uuid.UUID,
        upload_id: uuid.UUID,
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> UploadSessionRead:
        """Which chunks arrived. A client resumes by sending the ones that did not."""
        from service_projects.contracts import ensure_owned_project

        ensure_owned_project(db, project_id, current_user.id)
        return UploadSessionRead(
            **resumable.SESSIONS.get(db, upload_id, project_id=project_id).to_dict()
        )

    @router.put(
        '/projects/{project_id}/datasets/uploads/{upload_id}/chunks/{index}',
        response_model=UploadSessionRead,
    )
    async def put_chunk(
        project_id: uuid.UUID,
        upload_id: uuid.UUID,
        index: int,
        chunk: UploadFile = File(...),
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend = Depends(get_storage_backend),
    ) -> UploadSessionRead:
        """Send one chunk. Sending the same index again replaces it."""
        from service_projects.contracts import ensure_owned_project

        ensure_owned_project(db, project_id, current_user.id)
        try:
            session = resumable.SESSIONS.get(db, upload_id, project_id=project_id)
            payload = await chunk.read()
            resumable.receive_chunk(
                session, index=index, payload=payload, storage_backend=storage_backend
            )
            # Persist the arrival before answering: a restart between now and the
            # next chunk must still know this one landed.
            resumable.SESSIONS.save(db, session)
            return UploadSessionRead(**session.to_dict())
        finally:
            await chunk.close()

    @router.post(
        '/projects/{project_id}/datasets/uploads/{upload_id}/complete',
        response_model=DatasetUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def complete_upload(
        project_id: uuid.UUID,
        upload_id: uuid.UUID,
        dataset_name: str | None = Body(default=None, embed=True),
        spec_id: uuid.UUID | None = Body(default=None, embed=True),
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend = Depends(get_storage_backend),
    ) -> DatasetUploadResponse:
        """Assemble the chunks, verify them, and ingest the result."""
        from service_ingestion.schemas import IngestionUpload
        from service_projects.contracts import ensure_owned_project

        ensure_owned_project(db, project_id, current_user.id)
        session = resumable.SESSIONS.get(db, upload_id, project_id=project_id)
        payload = resumable.assemble(session, storage_backend=storage_backend)

        spec, record = _resolve_spec(
            db,
            project_id=project_id,
            spec_id=spec_id,
            file_name=session.file_name,
            current_user=current_user,
        )
        try:
            response = ingest_project_file(
                db,
                project_id=project_id,
                dataset_name=dataset_name,
                upload_file=IngestionUpload(
                    file_name=session.file_name,
                    content_type=session.content_type,
                    file_bytes=payload,
                ),
                storage_backend=storage_backend,
                settings=settings,
                current_user=current_user,
                ingest_spec=spec,
            )
        finally:
            # The session is done either way: a failed ingest of assembled
            # bytes is not something re-sending chunks would fix.
            resumable.SESSIONS.drop(db, upload_id)
        if record is not None:
            analysis_service.record_use(db, record)
            db.commit()
        return response

    @router.delete(
        '/projects/{project_id}/datasets/uploads/{upload_id}',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def abandon_upload(
        project_id: uuid.UUID,
        upload_id: uuid.UUID,
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend = Depends(get_storage_backend),
    ) -> None:
        from service_projects.contracts import ensure_owned_project

        ensure_owned_project(db, project_id, current_user.id)
        session = resumable.SESSIONS.get(db, upload_id, project_id=project_id)
        resumable.cleanup(session, storage_backend=storage_backend)
        resumable.SESSIONS.drop(db, upload_id)

    return router


def _parse_inline_spec(raw: str | None) -> dict | None:
    """The spec the upload screen sent, validated before anything is written."""
    import json

    from service_ingestion import spec as spec_module

    if not raw or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadRequestError(f'The ingest spec sent with this file is not valid JSON: {exc.msg}.') from exc
    if not isinstance(payload, dict):
        raise BadRequestError('An ingest spec must be an object.')
    # Validated here rather than deep in the reader, so a spec that could never
    # be applied is refused before the file is stored and a run is opened.
    spec_module.validate(spec_module.IngestSpec.from_dict(payload))
    return payload


def _resolve_spec(
    db,
    *,
    project_id: uuid.UUID,
    spec_id: uuid.UUID | None,
    file_name: str,
    current_user: UserRead,
):
    """The spec to read a file with, and the record it came from.

    A named spec is used as given. Without one, nothing is looked up here --
    the upload path infers, and `analyze` is where a saved spec gets offered,
    because applying one silently would change how a file reads without anybody
    being told.
    """
    if spec_id is None:
        return None, None
    record = analysis_service._get(db, project_id, spec_id)
    return dict(record.spec_json or {}), record
