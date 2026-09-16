"""Chunked, resumable upload.

The requirement is "a 2GB CSV uploads, resumes after an interruption, and does
not fail at 95%". What that actually means is tested here: chunks arrive out of
order, a retry of one chunk replaces rather than duplicates it, a truncated
chunk is caught by the checksum rather than becoming 99.97% of a dataset, and
one project cannot reach another's session.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from shared_python.errors import BadRequestError, NotFoundError

from service_ingestion import resumable


class FakeStorage:
    """Storage that keeps parts in a dict, the way the real one keeps files."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def save_upload(self, *, relative_path: str, file_bytes: bytes):
        self.files[relative_path] = file_bytes
        return type(
            "Stored",
            (),
            {
                "relative_path": relative_path,
                "file_name": relative_path.rsplit("/", 1)[-1],
                "size_bytes": len(file_bytes),
            },
        )()

    def read_bytes(self, relative_path: str) -> bytes:
        return self.files[relative_path]

    def exists(self, relative_path: str) -> bool:
        return relative_path in self.files

    def delete(self, relative_path: str) -> None:
        self.files.pop(relative_path, None)


@pytest.fixture()
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture()
def project() -> uuid.UUID:
    return uuid.uuid4()


def _session(project_id: uuid.UUID, payload: bytes, *, chunk: int = 16, checksum: bool = True):
    return resumable.SESSIONS.create(
        project_id=project_id,
        file_name="big.csv",
        content_type="text/csv",
        total_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest() if checksum else None,
        chunk_bytes=chunk,
    )


def _chunks(payload: bytes, size: int) -> list[bytes]:
    return [payload[index: index + size] for index in range(0, len(payload), size)]


PAYLOAD = b"id,name\n" + b"".join(f"{i},row-{i}\n".encode() for i in range(20))


class TestTheHappyPath:
    def test_chunks_assemble_into_the_original_file(self, project, storage) -> None:
        session = _session(project, PAYLOAD)
        for index, chunk in enumerate(_chunks(PAYLOAD, session.chunk_bytes)):
            resumable.receive_chunk(session, index=index, payload=chunk, storage_backend=storage)
        assert resumable.assemble(session, storage_backend=storage) == PAYLOAD

    def test_the_parts_are_cleaned_up_afterwards(self, project, storage) -> None:
        session = _session(project, PAYLOAD)
        for index, chunk in enumerate(_chunks(PAYLOAD, session.chunk_bytes)):
            resumable.receive_chunk(session, index=index, payload=chunk, storage_backend=storage)
        resumable.assemble(session, storage_backend=storage)
        assert storage.files == {}, "an assembled upload should leave no parts behind"


class TestResuming:
    def test_the_session_says_which_chunks_are_missing(self, project, storage) -> None:
        """The whole mechanism: a client asks what arrived and sends the rest."""
        session = _session(project, PAYLOAD)
        chunks = _chunks(PAYLOAD, session.chunk_bytes)
        for index in (0, 2):
            resumable.receive_chunk(
                session, index=index, payload=chunks[index], storage_backend=storage
            )
        assert 1 in session.missing
        assert 0 not in session.missing

    def test_an_interrupted_upload_finishes_by_sending_the_rest(self, project, storage) -> None:
        session = _session(project, PAYLOAD)
        chunks = _chunks(PAYLOAD, session.chunk_bytes)
        # The connection drops after two chunks.
        for index in range(2):
            resumable.receive_chunk(
                session, index=index, payload=chunks[index], storage_backend=storage
            )
        with pytest.raises(BadRequestError, match="incomplete"):
            resumable.assemble(session, storage_backend=storage)

        for index in session.missing[:]:
            resumable.receive_chunk(
                session, index=index, payload=chunks[index], storage_backend=storage
            )
        assert resumable.assemble(session, storage_backend=storage) == PAYLOAD

    def test_chunks_may_arrive_out_of_order(self, project, storage) -> None:
        session = _session(project, PAYLOAD)
        chunks = _chunks(PAYLOAD, session.chunk_bytes)
        for index in reversed(range(len(chunks))):
            resumable.receive_chunk(
                session, index=index, payload=chunks[index], storage_backend=storage
            )
        assert resumable.assemble(session, storage_backend=storage) == PAYLOAD

    def test_resending_a_chunk_replaces_it_rather_than_appending(self, project, storage) -> None:
        """A client that retried after a timeout it never saw is the common case."""
        session = _session(project, PAYLOAD)
        chunks = _chunks(PAYLOAD, session.chunk_bytes)
        for index, chunk in enumerate(chunks):
            resumable.receive_chunk(session, index=index, payload=chunk, storage_backend=storage)
        resumable.receive_chunk(session, index=0, payload=chunks[0], storage_backend=storage)
        assert resumable.assemble(session, storage_backend=storage) == PAYLOAD


class TestRefusals:
    def test_a_truncated_chunk_is_caught_by_the_checksum(self, project, storage) -> None:
        """A dataset that is 99.97% of a file is worse than a failed upload."""
        session = _session(project, PAYLOAD)
        chunks = _chunks(PAYLOAD, session.chunk_bytes)
        for index, chunk in enumerate(chunks):
            resumable.receive_chunk(session, index=index, payload=chunk, storage_backend=storage)
        # A proxy mangles one part after it was accepted.
        path = resumable.part_path(session, 1)
        storage.files[path] = storage.files[path][:-1] + b"X"

        with pytest.raises(BadRequestError, match="checksum"):
            resumable.assemble(session, storage_backend=storage)

    def test_a_short_middle_chunk_is_refused_on_arrival(self, project, storage) -> None:
        """Offsets stop lining up, and the assembled file is silently shuffled."""
        session = _session(project, PAYLOAD)
        with pytest.raises(BadRequestError, match="must be exactly"):
            resumable.receive_chunk(session, index=0, payload=b"short", storage_backend=storage)

    def test_a_chunk_past_the_end_is_refused(self, project, storage) -> None:
        session = _session(project, PAYLOAD)
        with pytest.raises(BadRequestError, match="outside this upload"):
            resumable.receive_chunk(
                session, index=999, payload=b"x" * session.chunk_bytes, storage_backend=storage
            )

    def test_an_empty_chunk_is_refused(self, project, storage) -> None:
        session = _session(project, PAYLOAD)
        with pytest.raises(BadRequestError, match="cannot be empty"):
            resumable.receive_chunk(session, index=0, payload=b"", storage_backend=storage)

    def test_a_declared_size_of_zero_is_refused(self, project) -> None:
        with pytest.raises(BadRequestError, match="positive"):
            resumable.SESSIONS.create(
                project_id=project, file_name="x.csv", content_type="", total_bytes=0
            )


class TestIsolation:
    def test_another_project_cannot_reach_this_session(self, project, storage) -> None:
        """An upload id is otherwise a guess away from another project's file."""
        session = _session(project, PAYLOAD)
        with pytest.raises(NotFoundError):
            resumable.SESSIONS.get(session.id, project_id=uuid.uuid4())
        assert resumable.SESSIONS.get(session.id, project_id=project) is session

    def test_an_unknown_upload_id_is_not_found(self, project) -> None:
        with pytest.raises(NotFoundError):
            resumable.SESSIONS.get(uuid.uuid4(), project_id=project)


class TestBounds:
    def test_a_huge_file_gets_larger_chunks_rather_than_a_refusal(self, project) -> None:
        """The ceiling bounds the number of parts, not the size of the upload."""
        huge = 200 * 1024 * 1024 * 1024  # 200GB
        session = resumable.SESSIONS.create(
            project_id=project, file_name="huge.csv", content_type="", total_bytes=huge
        )
        assert session.expected_chunks <= resumable.MAX_CHUNKS
        assert session.chunk_bytes > resumable.CHUNK_BYTES

    def test_a_two_gigabyte_file_is_a_few_hundred_requests(self, project) -> None:
        """The number the requirement is really about."""
        session = resumable.SESSIONS.create(
            project_id=project,
            file_name="orders.csv",
            content_type="text/csv",
            total_bytes=2 * 1024 * 1024 * 1024,
        )
        assert 200 <= session.expected_chunks <= 600
