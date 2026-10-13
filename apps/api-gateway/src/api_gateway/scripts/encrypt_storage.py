"""CLI: encrypt the files stored before STORAGE_ENCRYPTION_KEY was set.

Once the key is configured, new files are written encrypted and old ones keep
reading as they are. This encrypts the old ones in place, so every stored
file is ciphertext. Safe to run more than once: encrypted files are skipped.

    STORAGE_ENCRYPTION_KEY=... platform-encrypt-storage
    python -m api_gateway.scripts.encrypt_storage
"""

from __future__ import annotations

import sys

from api_gateway.config import settings
from shared_python.storage.factory import build_storage_backend


def main() -> None:
    backend = build_storage_backend(settings)
    if not getattr(backend, "encrypted", False):
        raise SystemExit(
            "STORAGE_ENCRYPTION_KEY is not set, so there is nothing to encrypt with. "
            "Set it (32 random bytes, base64), restart the platform, then run this again."
        )
    done, already = backend.encrypt_existing()
    print(f"Encrypted {done} file(s); {already} were already encrypted.")
    sys.exit(0)


if __name__ == "__main__":
    main()
