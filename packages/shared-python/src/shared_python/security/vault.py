"""Where secrets actually live.

Until now a connector's password was encrypted at rest with a Fernet key and
stored in the config JSON, which is correct and is not the whole story. At two
hundred connectors a deployment starts wanting the answer to be "it is in Vault"
or "it is in Secrets Manager" -- not because encryption-at-rest is wrong, but
because the key rotation, the audit trail and the access policy already exist
there and nobody wants a second copy of them here.

So a config value can now be a **reference** rather than a value:

    {"password": "vault://database/prod#password"}

The reference is resolved when the connector is used and never written back.
What is stored is the pointer; what is held in memory is the secret, briefly.

**The providers.** `env` and `file` need nothing and work everywhere. The
managed ones -- HashiCorp Vault, AWS Secrets Manager, Azure Key Vault -- need
their SDKs, and a deployment without the SDK gets a clear refusal rather than a
silent fallback to plaintext. That refusal is the point: falling back would
turn "our secrets are in Vault" into a sentence nobody could verify.

Nothing here changes the existing behaviour. A config value that is not a
reference is passed through untouched, so every connector configured before
this existed keeps working exactly as it did.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable

from shared_python.errors import BadRequestError

#: `scheme://path#key`, where the key is optional.
_REFERENCE = re.compile(r"^(?P<scheme>[a-z0-9_]+)://(?P<path>[^#\s]+)(?:#(?P<key>[^\s]+))?$")

#: Schemes this understands. Anything else is a literal value, not a typo --
#: a password genuinely can look like a URL, so an unknown scheme is left alone.
SCHEMES = ("env", "file", "vault", "awssm", "azurekv")


@dataclass(frozen=True)
class SecretRef:
    scheme: str
    path: str
    key: str | None = None

    def __str__(self) -> str:
        return f"{self.scheme}://{self.path}" + (f"#{self.key}" if self.key else "")

    @property
    def redacted(self) -> str:
        """Safe to log: the location is not the secret."""
        return str(self)


def parse_reference(value: Any) -> SecretRef | None:
    """A reference, or None when this is an ordinary value."""
    if not isinstance(value, str):
        return None
    match = _REFERENCE.match(value.strip())
    if match is None or match.group("scheme") not in SCHEMES:
        return None
    return SecretRef(
        scheme=match.group("scheme"), path=match.group("path"), key=match.group("key")
    )


class SecretsError(BadRequestError):
    """A reference that could not be resolved, said in terms of the reference."""


Resolver = Callable[[SecretRef], str]
_PROVIDERS: dict[str, Resolver] = {}


def register_provider(scheme: str, resolver: Resolver) -> None:
    """Add a backend. Used by deployments with their own secret store."""
    if scheme not in SCHEMES:
        raise ValueError(f"'{scheme}' is not a known scheme. Known: {', '.join(SCHEMES)}.")
    _PROVIDERS[scheme] = resolver


def available_schemes() -> list[str]:
    """Which backends this deployment can actually resolve."""
    return sorted(scheme for scheme in SCHEMES if scheme in _PROVIDERS)


def resolve(value: Any) -> Any:
    """Turn a reference into its secret. Ordinary values pass through."""
    reference = parse_reference(value)
    if reference is None:
        return value
    provider = _PROVIDERS.get(reference.scheme)
    if provider is None:
        raise SecretsError(
            f"This deployment cannot resolve {reference.redacted}: no "
            f"'{reference.scheme}' provider is configured. Available: "
            f"{', '.join(available_schemes()) or 'none'}."
        )
    resolved = provider(reference)
    if not resolved:
        raise SecretsError(f"{reference.redacted} resolved to nothing.")
    return resolved


def resolve_config(config: dict[str, Any], field_names: tuple[str, ...]) -> dict[str, Any]:
    """Resolve every reference among the named fields.

    Called at the point of use, alongside decryption, so a stored reference and
    a stored ciphertext are interchangeable from the connector's point of view.
    """
    out = dict(config)
    for name in field_names:
        if name in out:
            out[name] = resolve(out[name])
    return out


def references_in(config: dict[str, Any], field_names: tuple[str, ...]) -> dict[str, str]:
    """Which of these fields are references, for showing in a config form."""
    found: dict[str, str] = {}
    for name in field_names:
        reference = parse_reference(config.get(name))
        if reference is not None:
            found[name] = reference.redacted
    return found


# ------------------------------------------------------------- the providers


def _from_env(reference: SecretRef) -> str:
    name = reference.key or reference.path
    value = os.environ.get(name)
    if value is None:
        raise SecretsError(
            f"{reference.redacted} names an environment variable that is not set."
        )
    return value


def _from_file(reference: SecretRef) -> str:
    """A file on disk, which is how a container orchestrator mounts a secret."""
    import json
    from pathlib import Path

    path = Path(reference.path)
    if not path.is_file():
        raise SecretsError(f"{reference.redacted} names a file that does not exist.")
    body = path.read_text(encoding="utf-8").strip()
    if reference.key is None:
        return body
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SecretsError(
            f"{reference.redacted} asks for a key, but that file is not JSON."
        ) from exc
    if reference.key not in document:
        raise SecretsError(f"{reference.redacted} names a key that file does not have.")
    return str(document[reference.key])


register_provider("env", _from_env)
register_provider("file", _from_file)


def install_managed_providers() -> list[str]:
    """Wire up the managed stores whose SDKs are installed.

    Called once at startup. A store whose SDK is absent is simply not
    registered, so a reference to it fails with "no provider is configured"
    rather than silently reading something else. There is no fallback to
    plaintext, deliberately: falling back would make "our secrets are in Vault"
    a sentence nobody could check.
    """
    installed: list[str] = []

    try:
        import hvac  # noqa: F401

        def _from_vault(reference: SecretRef) -> str:
            client = hvac.Client(
                url=os.environ.get("VAULT_ADDR", ""), token=os.environ.get("VAULT_TOKEN", "")
            )
            mount, _, path = reference.path.partition("/")
            response = client.secrets.kv.v2.read_secret_version(path=path, mount_point=mount)
            data = (response or {}).get("data", {}).get("data", {})
            if reference.key is None:
                raise SecretsError(f"{reference.redacted} needs a #key naming the field.")
            if reference.key not in data:
                raise SecretsError(f"{reference.redacted} names a field that secret does not have.")
            return str(data[reference.key])

        register_provider("vault", _from_vault)
        installed.append("vault")
    except ImportError:
        pass

    try:
        import boto3  # noqa: F401

        def _from_aws(reference: SecretRef) -> str:
            import json

            client = boto3.client("secretsmanager")
            response = client.get_secret_value(SecretId=reference.path)
            body = response.get("SecretString") or ""
            if reference.key is None:
                return body
            try:
                document = json.loads(body)
            except json.JSONDecodeError as exc:
                raise SecretsError(
                    f"{reference.redacted} asks for a key, but that secret is not JSON."
                ) from exc
            if reference.key not in document:
                raise SecretsError(f"{reference.redacted} names a key that secret does not have.")
            return str(document[reference.key])

        register_provider("awssm", _from_aws)
        installed.append("awssm")
    except ImportError:
        pass

    try:
        from azure.identity import DefaultAzureCredential  # noqa: F401
        from azure.keyvault.secrets import SecretClient  # noqa: F401

        def _from_azure(reference: SecretRef) -> str:
            from azure.identity import DefaultAzureCredential as Credential
            from azure.keyvault.secrets import SecretClient as Client

            vault, _, name = reference.path.partition("/")
            client = Client(vault_url=f"https://{vault}.vault.azure.net", credential=Credential())
            return str(client.get_secret(name).value)

        register_provider("azurekv", _from_azure)
        installed.append("azurekv")
    except ImportError:
        pass

    return installed


def describe() -> dict[str, Any]:
    """What a deployment can resolve, for the health view."""
    return {
        "schemes": list(SCHEMES),
        "available": available_schemes(),
        "unavailable": [scheme for scheme in SCHEMES if scheme not in _PROVIDERS],
        "example": "vault://database/prod#password",
    }
