from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _app_secret_encryption_key() -> None:
    key = Fernet.generate_key().decode()
    prev = os.environ.get("APP_SECRET_ENCRYPTION_KEY")
    os.environ["APP_SECRET_ENCRYPTION_KEY"] = key
    yield
    if prev is None:
        os.environ.pop("APP_SECRET_ENCRYPTION_KEY", None)
    else:
        os.environ["APP_SECRET_ENCRYPTION_KEY"] = prev
