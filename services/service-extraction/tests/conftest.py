from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

# The suite runs with --import-mode=importlib, which puts no test folder on the
# path; the live-source tests share `live_servers.py`, the one table of where
# the test servers are, with scripts/check-live-servers.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def _extraction_encryption_key(monkeypatch) -> None:
    """Settings with secrets are encrypted at rest; CI has no key in a .env."""
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
