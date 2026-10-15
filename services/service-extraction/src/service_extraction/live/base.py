"""What every live-source kind declares and does (D1, roadmap Phase 20).

A live source delivers rows instead of being asked for them: a webhook, a
database's change log, or a message queue. Each kind is one class here with
the same small surface, so the runner, the API and the form in the web app
never learn what Kafka or a binary log is:

- **declares** its settings (secrets encrypted at rest), its family, how
  sure it is that each event is saved once, and how verified it is;
- **tests** settings before they are saved, saying what to change in the
  source's own words;
- **reads** a batch from a saved position, returning the events, the
  position to save *with* them, and what to do once they are saved
  (acknowledge, or advance a replication slot).

Change-capture kinds also take a position before a snapshot, read each
table's rows for the snapshot, and name each table's key.

Every read is micro-batch: connect, read up to a limit, return. Nothing
holds a connection between passes.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal


Family = Literal["webhook", "change_capture", "queue"]
Guarantee = Literal["position", "message_id", "at_least_once"]

#: What each guarantee means, as the form and the source's page say it.
GUARANTEES: dict[str, tuple[str, str]] = {
    "position": (
        "Each event is saved once",
        "Its position is saved with the events, so after a restart reading carries on from there "
        "and nothing is saved twice.",
    ),
    "message_id": (
        "Each event is saved once, by its id",
        "Events are acknowledged after they are saved; one that is delivered again is recognised by "
        "its id and skipped.",
    ),
    "at_least_once": (
        "Each event is saved at least once",
        "Events are acknowledged after they are saved. If Pipewright stops in between, the source "
        "sends them again and one can be saved twice.",
    ),
}

#: Positions longer than this are stored as a digest; the column is 64 wide.
_POSITION_WIDTH = 64


class LiveError(Exception):
    """A failure in the source's own words, safe to show to the person."""


@dataclass(frozen=True)
class LiveField:
    """One setting on the form. `kind` is how the form draws it."""

    key: str
    label: str
    kind: Literal["string", "secret", "number", "boolean", "select", "text"] = "string"
    required: bool = True
    default: Any = None
    help: str = ""
    placeholder: str = ""
    options: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "kind": self.kind, "required": self.required,
            "default": self.default, "help": self.help, "placeholder": self.placeholder,
            "options": list(self.options),
        }


@dataclass
class Message:
    """One thing that arrived.

    `kind` is `message` for a queue or webhook, `insert`/`update`/`delete`
    for a row change. `position` identifies it within the source, so storing
    it twice is skipped; None when the source gives nothing to recognise a
    redelivery by.
    """

    kind: str
    payload: dict[str, Any]
    position: str | None = None
    table: str | None = None


@dataclass
class Batch:
    messages: list[Message] = field(default_factory=list)
    #: The position to save in the same transaction as the events, for kinds
    #: that own their position. None leaves the saved one as it is.
    cursor: dict[str, Any] | None = None
    #: Called once the events are committed: acknowledge them, advance a slot.
    after_commit: Callable[[], None] | None = None
    #: Called when the events could not be saved: let the source send them again.
    abandon: Callable[[], None] | None = None
    #: The source had more waiting than this batch took.
    more: bool = False
    #: How far behind the source the saved position is, when the source says.
    behind: int | None = None
    notes: list[str] = field(default_factory=list)

    def finish(self, saved: bool) -> None:
        action = self.after_commit if saved else self.abandon
        if action is not None:
            action()


@dataclass
class Outcome:
    """A test of settings: whether reading would work, and what to change."""

    ok: bool
    message: str
    details: list[str] = field(default_factory=list)


class LiveKind:
    key: str = ""
    label: str = ""
    family: Family = "queue"
    description: str = ""
    fields: tuple[LiveField, ...] = ()
    #: Change-capture kinds that read through a project connection name its type.
    connection_types: tuple[str, ...] = ()
    guarantee: Guarantee = "at_least_once"
    #: A sentence that sharpens the guarantee for this kind, when it needs one.
    guarantee_note: str = ""
    #: The connector tier (1-4) this kind has earned; see `service_connectors.protocol.Tier`.
    tier: int = 2
    verified_by: str = ""
    #: The package that must be importable, or None when nothing extra is needed.
    driver_module: str | None = None
    driver_package: str | None = None

    @property
    def secret_fields(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields if f.kind == "secret")

    def available(self) -> tuple[bool, str | None]:
        if not self.driver_module:
            return True, None
        try:
            __import__(self.driver_module)
        except ImportError:
            return False, f"{self.label} needs the '{self.driver_package}' package, which is not installed here."
        return True, None

    def validate(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Settings with defaults filled in; a missing required one is refused by name."""
        out: dict[str, Any] = {}
        for item in self.fields:
            value = settings.get(item.key)
            if value is None or (isinstance(value, str) and not value.strip()):
                if item.required and item.default is None:
                    raise LiveError(f"{item.label} is needed.")
                value = item.default
            elif item.kind == "number":
                try:
                    value = int(value)
                except (TypeError, ValueError) as exc:
                    raise LiveError(f"{item.label} must be a whole number.") from exc
            elif item.kind == "boolean":
                value = bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "yes", "on")
            elif item.kind == "select" and item.options and value not in item.options:
                raise LiveError(f"{item.label} must be one of {', '.join(item.options)}.")
            elif isinstance(value, str):
                value = value.strip()
            out[item.key] = value
        return out

    def describe(self) -> dict[str, Any]:
        from service_connectors.protocol import Tier  # the catalogue's tiers, one definition

        ok, reason = self.available()
        title, detail = GUARANTEES[self.guarantee]
        tier = Tier(self.tier)
        return {
            "key": self.key, "label": self.label, "family": self.family, "description": self.description,
            "fields": [f.to_dict() for f in self.fields], "connection_types": list(self.connection_types),
            "guarantee": self.guarantee, "guarantee_title": title,
            "guarantee_detail": f"{detail} {self.guarantee_note}".strip(),
            "tier": int(tier), "tier_label": tier.label, "tier_badge": tier.badge,
            "tier_explanation": tier.explanation, "verified_by": self.verified_by,
            "available": ok, "unavailable_reason": reason,
        }

    # -- what a kind does -------------------------------------------------

    def test(self, settings: dict[str, Any]) -> Outcome:  # pragma: no cover - every kind overrides
        raise NotImplementedError

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:  # pragma: no cover
        raise NotImplementedError

    def forget(self, settings: dict[str, Any]) -> None:
        """Release what the source holds open on the far side (a replication slot)."""
        return None

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        """The addresses reading would call, which the outbound guard checks first.
        Kinds that read through a saved connection reach it as imports do."""
        return []

    def guard(self, settings: dict[str, Any]) -> None:
        """Refuse an address the platform must not call (`shared_python.outbound`)."""
        from shared_python.outbound import OutboundBlocked, check_host

        for host in self.hosts(settings):
            try:
                check_host(host)
            except OutboundBlocked as exc:
                raise LiveError(f"{exc} Pipewright will not read from there.") from exc


class ChangeCaptureKind(LiveKind):
    family: Family = "change_capture"
    guarantee: Guarantee = "position"

    def start_position(self, settings: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        """Where the change log is now; reading from here after a snapshot misses nothing."""
        raise NotImplementedError

    def key_columns(self, settings: dict[str, Any], table: str) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def snapshot(self, settings: dict[str, Any], table: str, *, chunk: int) -> Iterator[list[dict[str, Any]]]:  # pragma: no cover
        """Every row of the table, in key order, in chunks."""
        raise NotImplementedError


# ------------------------------------------------------------------ helpers


def position_of(raw: str | None) -> str | None:
    """A stored position: the source's own when it fits, a digest when not."""
    if raw is None:
        return None
    if len(raw) <= _POSITION_WIDTH:
        return raw
    return "h:" + hashlib.sha256(raw.encode()).hexdigest()[: _POSITION_WIDTH - 2]


def plain(value: Any) -> Any:
    """A value the event store (JSON) can hold, as close to the original as it can."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() and abs(value) < 2**53 else float(value)
    if isinstance(value, datetime):
        # A time without a zone stays without one: adding UTC would be a claim.
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return "base64:" + base64.b64encode(raw).decode()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def decode_body(raw: bytes | str | None) -> tuple[Any, str]:
    """A message body as JSON when it is JSON, else text. Returns (value, how)."""
    if raw is None:
        return None, "empty"
    if isinstance(raw, (bytes, bytearray, memoryview)):
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            return "base64:" + base64.b64encode(bytes(raw)).decode(), "binary"
    else:
        text = raw
    stripped = text.strip()
    if stripped[:1] in ("{", "[") or stripped in ("true", "false", "null") or _looks_numeric(stripped):
        try:
            return json.loads(stripped), "json"
        except json.JSONDecodeError:
            pass
    return text, "text"


def _looks_numeric(text: str) -> bool:
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def queue_payload(*, value: Any, key: Any = None, headers: dict[str, Any] | None = None,
                  published_at: datetime | str | None = None, **where: Any) -> dict[str, Any]:
    """The payload every queue message is stored as."""
    body, how = decode_body(value) if isinstance(value, (bytes, bytearray, memoryview, str)) or value is None else (value, "json")
    if isinstance(key, (bytes, bytearray, memoryview)):
        try:
            key = bytes(key).decode("utf-8")  # a key is a name, not a document
        except UnicodeDecodeError:
            key = "base64:" + base64.b64encode(bytes(key)).decode()
    payload: dict[str, Any] = {"value": plain(body), "format": how}
    if key is not None:
        payload["key"] = plain(key)
    if headers:
        payload["headers"] = {str(k): plain(v) for k, v in headers.items()}
    if published_at is not None:
        payload["published_at"] = plain(published_at)
    for name, item in where.items():
        if item is not None:
            payload[name] = plain(item)
    return payload


def host_of(address: str | None, *, default_scheme: str = "tcp") -> str | None:
    """The host in `host:port`, `scheme://user@host:port/path` or `[::1]:port`."""
    from urllib.parse import urlsplit

    text = (address or "").strip()
    if not text:
        return None
    parsed = urlsplit(text if "://" in text else f"{default_scheme}://{text}")
    return parsed.hostname


def epoch_ms(value: int | float | None) -> datetime | None:
    if value is None or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)
