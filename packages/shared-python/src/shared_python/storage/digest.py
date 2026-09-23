"""Content digests for stored artifacts.

Time travel (Phase 18) records an immutable version each time a dataset is
materialised. A version needs a stable fingerprint of the bytes it published:
two versions with the same digest hold the same data, which is what lets a later
increment deduplicate storage and lets a diff shortcut "these are identical"
without reading either file.

The digest is deliberately a self-describing string -- ``sha256:<hex>`` -- so the
algorithm travels with the value. If the algorithm ever changes, old digests stay
unambiguous rather than becoming bare hex that could be anything.
"""

from __future__ import annotations

import hashlib

#: The one algorithm in use. Named so a stored digest says how it was computed.
DIGEST_ALGORITHM = "sha256"


def content_digest(data: bytes) -> str:
    """Return ``sha256:<hex>`` for ``data``.

    Stable across processes and machines (unlike ``hash()``), so it is safe to
    persist and to compare between a fresh materialisation and a stored version.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("content_digest expects bytes.")
    return f"{DIGEST_ALGORITHM}:{hashlib.sha256(bytes(data)).hexdigest()}"
