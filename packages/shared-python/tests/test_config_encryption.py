from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from shared_python.errors import MisconfiguredEnvironmentError
from shared_python.security.config_crypto import decrypt_sensitive_fields, encrypt_sensitive_fields
from shared_python.security.encryption import STORED_SECRET_PREFIX, decrypt_secret_value, encrypt_secret_value


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", key)
    c = encrypt_secret_value("hello")
    assert c.startswith(STORED_SECRET_PREFIX)
    assert decrypt_secret_value(c) == "hello"


def test_decrypt_plaintext_legacy_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert decrypt_secret_value("plain-password") == "plain-password"


def test_encrypt_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_SECRET_ENCRYPTION_KEY", raising=False)
    with pytest.raises(MisconfiguredEnvironmentError):
        encrypt_secret_value("x")


def test_sensitive_field_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    d = encrypt_sensitive_fields({"host": "h", "password": "pw"}, ("password",))
    assert d["host"] == "h"
    assert d["password"].startswith(STORED_SECRET_PREFIX)
    p = decrypt_sensitive_fields(d, ("password",))
    assert p["password"] == "pw"


def test_decrypt_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    secret = encrypt_secret_value("x")
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(MisconfiguredEnvironmentError):
        decrypt_secret_value(secret)


def test_encrypt_idempotent_on_stored_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    once = encrypt_secret_value("abc")
    assert encrypt_secret_value(once) == once
