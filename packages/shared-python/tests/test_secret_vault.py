"""Secret references, and the refusals that keep them honest.

The design question this answers: how does a deployment say "our database
passwords live in Vault" in a way anybody can verify? By storing a pointer
instead of a value, resolving it at the point of use, and refusing -- loudly --
when the store is not reachable. A silent fallback to plaintext would make the
claim unfalsifiable, which is the same failure the connector tier system exists
to prevent.
"""

from __future__ import annotations

import json

import pytest

from shared_python.security import vault
from shared_python.security.config_crypto import (
    decrypt_sensitive_fields,
    encrypt_sensitive_fields,
)


class TestParsing:
    def test_it_recognises_a_reference(self) -> None:
        reference = vault.parse_reference("vault://database/prod#password")
        assert reference is not None
        assert (reference.scheme, reference.path, reference.key) == ("vault", "database/prod", "password")

    def test_the_key_is_optional(self) -> None:
        reference = vault.parse_reference("env://DB_PASSWORD")
        assert reference is not None
        assert reference.key is None

    def test_an_ordinary_password_is_not_a_reference(self) -> None:
        for value in ("hunter2", "", "  ", "s3cr3t://not-a-scheme", None, 42):
            assert vault.parse_reference(value) is None

    def test_a_connection_string_is_left_alone(self) -> None:
        # A password genuinely can look like a URL, so an unknown scheme is a
        # literal value rather than a typo to be second-guessed.
        assert vault.parse_reference("postgres://user:pw@host/db") is None

    def test_a_reference_is_safe_to_log(self) -> None:
        reference = vault.parse_reference("vault://database/prod#password")
        assert reference.redacted == "vault://database/prod#password"


class TestResolving:
    def test_a_plain_value_passes_through(self) -> None:
        assert vault.resolve("hunter2") == "hunter2"

    def test_env_reads_the_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("PIPEWRIGHT_TEST_SECRET", "hunter2")
        assert vault.resolve("env://PIPEWRIGHT_TEST_SECRET") == "hunter2"

    def test_a_missing_environment_variable_says_which(self, monkeypatch) -> None:
        monkeypatch.delenv("PIPEWRIGHT_ABSENT", raising=False)
        with pytest.raises(vault.SecretsError, match="PIPEWRIGHT_ABSENT"):
            vault.resolve("env://PIPEWRIGHT_ABSENT")

    def test_file_reads_a_mounted_secret(self, tmp_path) -> None:
        # How every container orchestrator delivers one.
        path = tmp_path / "db-password"
        path.write_text("hunter2\n")
        assert vault.resolve(f"file://{path}") == "hunter2"

    def test_file_can_take_a_key_out_of_json(self, tmp_path) -> None:
        path = tmp_path / "creds.json"
        path.write_text(json.dumps({"username": "ada", "password": "hunter2"}))
        assert vault.resolve(f"file://{path}#password") == "hunter2"

    def test_a_missing_file_says_so(self, tmp_path) -> None:
        with pytest.raises(vault.SecretsError, match="does not exist"):
            vault.resolve(f"file://{tmp_path / 'nope'}")

    def test_a_missing_key_says_so(self, tmp_path) -> None:
        path = tmp_path / "creds.json"
        path.write_text(json.dumps({"username": "ada"}))
        with pytest.raises(vault.SecretsError, match="names a key"):
            vault.resolve(f"file://{path}#password")

    def test_a_mount_path_with_a_space_in_it_is_still_a_reference(self, tmp_path) -> None:
        """The silent one.

        The path pattern excluded whitespace, so `file:///mnt/my secrets/db`
        did not parse, `resolve()` decided it was an ordinary value, and the
        caller got the reference string back to use as a password. Nothing
        raised. A connector would have authenticated with the literal text
        "file:///mnt/my secrets/db-password".
        """
        directory = tmp_path / "my secrets"
        directory.mkdir()
        path = directory / "db-password"
        path.write_text("hunter2\n")
        assert vault.parse_reference(f"file://{path}") is not None
        assert vault.resolve(f"file://{path}") == "hunter2"

    def test_a_key_may_contain_a_space(self, tmp_path) -> None:
        path = tmp_path / "creds.json"
        path.write_text(json.dumps({"the password": "hunter2"}))
        assert vault.resolve(f"file://{path}#the password") == "hunter2"

    def test_a_missing_file_on_a_spaced_path_still_says_so(self, tmp_path) -> None:
        """Failing to parse it used to mean failing to complain about it."""
        directory = tmp_path / "my secrets"
        directory.mkdir()
        with pytest.raises(vault.SecretsError, match="does not exist"):
            vault.resolve(f"file://{directory / 'nope'}")

    def test_an_unconfigured_store_refuses_rather_than_falling_back(self) -> None:
        """The important one.

        If this returned the reference string, or an empty password, a
        deployment would silently connect with the wrong credential -- or worse,
        believe its secrets were in Vault when nothing was reading Vault.
        """
        with pytest.raises(vault.SecretsError, match="no 'vault' provider is configured"):
            vault.resolve("vault://database/prod#password")

    def test_the_refusal_lists_what_is_available(self) -> None:
        with pytest.raises(vault.SecretsError, match="env"):
            vault.resolve("azurekv://myvault/db-password")

    def test_a_provider_returning_nothing_is_an_error(self, monkeypatch) -> None:
        monkeypatch.setenv("PIPEWRIGHT_EMPTY", "")
        with pytest.raises(vault.SecretsError):
            vault.resolve("env://PIPEWRIGHT_EMPTY")


class TestConfigIntegration:
    FIELDS = ("password", "api_key")

    @pytest.fixture(autouse=True)
    def _encryption_key(self, monkeypatch):
        # Encryption at rest needs the deployment's key; the vault path does
        # not, which is half of what these tests are checking.
        from cryptography.fernet import Fernet

        monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())

    def test_a_reference_is_stored_as_a_pointer_not_encrypted(self) -> None:
        # Encrypting the pointer would hide which store a connection reads.
        config = {"password": "vault://database/prod#password", "host": "db"}
        stored = encrypt_sensitive_fields(config, self.FIELDS)
        assert stored["password"] == "vault://database/prod#password"

    def test_an_ordinary_secret_is_still_encrypted(self) -> None:
        stored = encrypt_sensitive_fields({"password": "hunter2"}, self.FIELDS)
        assert stored["password"] != "hunter2"
        assert decrypt_sensitive_fields(stored, self.FIELDS)["password"] == "hunter2"

    def test_both_kinds_resolve_the_same_way_at_the_point_of_use(self, monkeypatch) -> None:
        monkeypatch.setenv("PIPEWRIGHT_DB_PASSWORD", "hunter2")
        by_reference = encrypt_sensitive_fields(
            {"password": "env://PIPEWRIGHT_DB_PASSWORD"}, self.FIELDS
        )
        by_value = encrypt_sensitive_fields({"password": "hunter2"}, self.FIELDS)
        # A connector cannot tell which it was given, which is the point.
        assert decrypt_sensitive_fields(by_reference, self.FIELDS)["password"] == "hunter2"
        assert decrypt_sensitive_fields(by_value, self.FIELDS)["password"] == "hunter2"

    def test_untouched_fields_are_left_alone(self) -> None:
        config = {"host": "db.internal", "port": 5432}
        assert encrypt_sensitive_fields(config, self.FIELDS) == config
        assert decrypt_sensitive_fields(config, self.FIELDS) == config

    def test_a_config_form_can_show_which_fields_are_references(self) -> None:
        config = {"password": "env://DB_PASSWORD", "api_key": "literal"}
        assert vault.references_in(config, self.FIELDS) == {"password": "env://DB_PASSWORD"}


class TestCapabilityReporting:
    def test_it_says_which_stores_this_deployment_can_read(self) -> None:
        """Available and unavailable partition the schemes, with nothing implied.

        Which of the managed stores is available depends on what is installed
        *and* on whether the gateway has started in this process -- boto3 is a
        dependency of the S3 connector, so `awssm` registers here and Vault does
        not. The contract is the partition, not which side any one lands on.
        """
        described = vault.describe()
        assert "env" in described["available"]
        assert "file" in described["available"]
        assert set(described["available"]) | set(described["unavailable"]) == set(
            described["schemes"]
        )
        assert not set(described["available"]) & set(described["unavailable"])

    def test_an_unregistered_store_is_reported_as_unavailable(self, monkeypatch) -> None:
        # Whatever is missing here, asking for it refuses rather than falling
        # back -- which is the property the partition exists to guarantee.
        for scheme in vault.describe()["unavailable"]:
            with pytest.raises(vault.SecretsError, match="no '" + scheme + "' provider"):
                vault.resolve(f"{scheme}://somewhere#key")

    def test_installing_managed_providers_is_safe_without_their_sdks(self) -> None:
        # Called at startup on every deployment, including this one.
        installed = vault.install_managed_providers()
        assert isinstance(installed, list)

    def test_an_unknown_scheme_cannot_be_registered(self) -> None:
        with pytest.raises(ValueError, match="not a known scheme"):
            vault.register_provider("wibble", lambda reference: "x")
