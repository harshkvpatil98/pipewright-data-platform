"""What the file is wrapped in, before asking what it is.

A `.csv.gz` is not a CSV until it has been unwrapped, and an archive is not one
file at all. Detection is by magic bytes rather than by extension: a file
renamed `report.csv` that is really a zip is common enough (Excel exports, mail
gateways) that trusting the name produces a parse error nobody can explain.

Archives are the interesting case. A zip of twelve monthly CSVs is twelve
datasets, or one if the schemas match -- and which of those somebody wants is
not something this module may decide. It reports the members and lets the
caller offer the choice.
"""

from __future__ import annotations

import bz2
import gzip
import io
import lzma
import tarfile
import zipfile
from dataclasses import dataclass, field
from typing import Any

from shared_python.errors import BadRequestError

from service_ingestion.sniff.evidence import Finding, certain, preview_bytes

#: Containers this platform can open, and the bytes that identify each.
MAGIC: tuple[tuple[str, bytes], ...] = (
    ("gzip", b"\x1f\x8b"),
    ("bzip2", b"BZh"),
    ("xz", b"\xfd7zXZ\x00"),
    ("zip", b"PK\x03\x04"),
    ("zstd", b"\x28\xb5\x2f\xfd"),
    ("7z", b"7z\xbc\xaf\x27\x1c"),
)

#: Containers named here but not openable on this deployment, with the reason.
#: Declared rather than omitted so "why did my .7z fail" has an answer.
UNSUPPORTED = {
    "7z": "7-Zip archives need the 'py7zr' package, which is not installed here.",
    "zstd": "Zstandard needs the 'zstandard' package, which is not installed here.",
}

#: A compressed file that expands beyond this is refused. A 40KB gzip can
#: expand to 10GB -- a zip bomb is the oldest way to take a service down, and
#: "read it and see" is how you find out too late.
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024

#: How many members of an archive are reported. An archive with ten thousand
#: entries is a directory tree, not a dataset.
MAX_ARCHIVE_MEMBERS = 200


@dataclass
class Member:
    """One file inside an archive."""

    name: str
    size_bytes: int
    payload: bytes | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size_bytes": self.size_bytes}


@dataclass
class Unwrapped:
    """The payload to carry on with, and what had to be removed to get it."""

    payload: bytes
    #: "none", or the container that was stripped.
    container: str
    finding: Finding
    #: Set when the container held more than one usable file.
    members: list[Member] = field(default_factory=list)

    @property
    def is_archive(self) -> bool:
        return bool(self.members)

    def to_dict(self) -> dict[str, Any]:
        return {
            "container": self.container,
            "finding": self.finding.to_dict(),
            "members": [member.to_dict() for member in self.members],
        }


#: Zip members that mean "this zip is a document, not an archive".
#: An `.xlsx` is a zip, and so are `.docx`, `.odt` and a Java `.jar`. Unwrapping
#: one hands the format detector a fragment of XML from inside it and the read
#: fails with a message about the wrong thing entirely.
DOCUMENT_MARKERS = (
    b"[Content_Types].xml",   # OOXML: xlsx, docx, pptx
    b"mimetypeapplication/vnd.oasis",  # OpenDocument, stored first and uncompressed
    b"META-INF/MANIFEST.MF",  # jar
)


def is_document_zip(payload: bytes) -> bool:
    """True when a zip is one file format rather than a container of files."""
    if not payload.startswith(b"PK\x03\x04"):
        return False
    # The markers live in the first entry or the central directory; checking
    # both ends covers how each format lays itself out without unzipping.
    return any(
        marker in payload[:8192] or marker in payload[-8192:]
        for marker in DOCUMENT_MARKERS
    )


def detect(payload: bytes) -> str:
    """The container, from the file's own first bytes."""
    if is_document_zip(payload):
        return "none"
    for name, magic in MAGIC:
        if payload.startswith(magic):
            return name
    return "none"


def _guard(size: int, container: str) -> None:
    if size > MAX_EXPANDED_BYTES:
        raise BadRequestError(
            f"This {container} expands to {size / 1024 ** 3:.1f}GB, past the "
            f"{MAX_EXPANDED_BYTES / 1024 ** 3:.0f}GB limit. Split it, or upload the "
            "files individually."
        )


def _decompress_stream(reader, container: str) -> bytes:
    """Read a decompressing stream with a ceiling, rather than to the end.

    `gzip.decompress` reads the whole thing before anybody can object, so the
    limit has to be enforced while reading, not after.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = reader.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        _guard(total, container)
        chunks.append(chunk)
    return b"".join(chunks)


def unwrap(payload: bytes, *, file_name: str = "") -> Unwrapped:
    """Strip the container, or report the archive's members."""
    container = detect(payload)

    if container == "none":
        document_zip = is_document_zip(payload)
        return Unwrapped(
            payload=payload,
            container="none",
            finding=certain(
                "container",
                "none",
                (
                    "The file is a zip, but a zip that *is* a document — an Office or "
                    "OpenDocument file — so it is read as one file rather than unpacked."
                    if document_zip
                    else "The file is not compressed or archived."
                ),
                evidence=[preview_bytes(payload[:16])],
            ),
        )

    if container in UNSUPPORTED:
        raise BadRequestError(UNSUPPORTED[container])

    evidence = [f"Leading bytes: {preview_bytes(payload[:8], limit=8)}"]
    named = _extension_says(file_name)
    if named and named != container:
        # Worth saying out loud: it means the file was renamed, and the next
        # confusing thing that happens will probably be related.
        evidence.append(
            f"The name says '{named}' but the bytes say '{container}'; the bytes win."
        )

    if container == "gzip":
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as reader:
            body = _decompress_stream(reader, "gzip")
    elif container == "bzip2":
        body = _decompress_stream(bz2.BZ2File(io.BytesIO(payload)), "bzip2")
    elif container == "xz":
        body = _decompress_stream(lzma.LZMAFile(io.BytesIO(payload)), "xz")
    elif container == "zip":
        return _unwrap_zip(payload, evidence)
    else:  # pragma: no cover - MAGIC and the branches above are kept in step
        raise BadRequestError(f"'{container}' archives are not supported here.")

    if tarfile.is_tarfile(io.BytesIO(body)):
        # `.tar.gz` is two containers, and stopping after the first leaves a tar
        # header where the caller expects a header row.
        return _unwrap_tar(body, container, evidence)

    return Unwrapped(
        payload=body,
        container=container,
        finding=certain(
            "container",
            container,
            f"Decompressed {len(payload):,} bytes of {container} into {len(body):,}.",
            evidence=evidence,
        ),
    )


def _extension_says(file_name: str) -> str | None:
    lowered = file_name.lower()
    for suffix, container in (
        (".gz", "gzip"), (".bz2", "bzip2"), (".xz", "xz"),
        (".zip", "zip"), (".7z", "7z"), (".zst", "zstd"),
    ):
        if lowered.endswith(suffix):
            return container
    return None


#: Names inside an archive that are never data: editor leftovers, macOS
#: resource forks, checksums somebody shipped alongside the real file.
def _is_noise(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    if not base or name.endswith("/"):
        return True
    if base.startswith("._") or base in (".DS_Store", "Thumbs.db"):
        return True
    if name.startswith("__MACOSX/"):
        return True
    return base.endswith((".md5", ".sha1", ".sha256", ".sig"))


def _unwrap_zip(payload: bytes, evidence: list[str]) -> Unwrapped:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = [
            info for info in archive.infolist()
            if not info.is_dir() and not _is_noise(info.filename)
        ]
        if not entries:
            raise BadRequestError("This zip contains no files to read.")

        total = sum(info.file_size for info in entries)
        _guard(total, "zip")

        if len(entries) == 1:
            body = archive.read(entries[0].filename)
            return Unwrapped(
                payload=body,
                container="zip",
                finding=certain(
                    "container",
                    "zip",
                    f"A zip holding one file, '{entries[0].filename}'.",
                    evidence=evidence,
                ),
            )

        members = [
            Member(name=info.filename, size_bytes=info.file_size, payload=archive.read(info.filename))
            for info in entries[:MAX_ARCHIVE_MEMBERS]
        ]

    return _archive_result("zip", members, len(entries), evidence)


def _unwrap_tar(body: bytes, outer: str, evidence: list[str]) -> Unwrapped:
    with tarfile.open(fileobj=io.BytesIO(body)) as archive:
        entries = [
            info for info in archive.getmembers()
            if info.isfile() and not _is_noise(info.name)
        ]
        if not entries:
            raise BadRequestError("This archive contains no files to read.")
        total = sum(info.size for info in entries)
        _guard(total, "tar")

        if len(entries) == 1:
            extracted = archive.extractfile(entries[0])
            payload = extracted.read() if extracted else b""
            return Unwrapped(
                payload=payload,
                container=f"{outer}+tar",
                finding=certain(
                    "container",
                    f"{outer}+tar",
                    f"A {outer} tar holding one file, '{entries[0].name}'.",
                    evidence=evidence,
                ),
            )

        members = []
        for info in entries[:MAX_ARCHIVE_MEMBERS]:
            extracted = archive.extractfile(info)
            members.append(
                Member(name=info.name, size_bytes=info.size, payload=extracted.read() if extracted else b"")
            )

    return _archive_result(f"{outer}+tar", members, len(entries), evidence)


def _archive_result(
    container: str, members: list[Member], total: int, evidence: list[str]
) -> Unwrapped:
    """A multi-file archive: reported, never silently collapsed.

    The first member is carried forward so a caller that only wants a preview
    gets one, but `members` is what the caller is expected to act on -- twelve
    monthly files are twelve datasets or one union, and that is the user's call.
    """
    if total > len(members):
        evidence.append(
            f"Showing the first {len(members)} of {total} files in the archive."
        )
    return Unwrapped(
        payload=members[0].payload or b"",
        container=container,
        members=members,
        finding=Finding(
            stage="container",
            value=container,
            certainty=certain("container", container, "").certainty,
            confidence=1.0,
            reason=(
                f"An archive of {total} files. Each can become its own dataset, or "
                "one dataset if their columns match."
            ),
            evidence=evidence + [member.name for member in members[:10]],
        ),
    )
