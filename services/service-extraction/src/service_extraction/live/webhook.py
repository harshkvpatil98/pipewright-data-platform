"""Webhooks: an address a partner posts events to (D1, roadmap Phase 20).

Nothing is read: whatever is posted to the address (keyed by a token shown
once and hashed at rest) is stored as an event as it arrives. A sender that
retries a post it was not sure got through sends it twice; one that puts an
`Idempotency-Key` header on each post has the repeat recognised and skipped.
"""

from __future__ import annotations

from typing import Any

from service_extraction.live.base import Batch, LiveKind, Outcome

#: Request headers kept with each event, besides the idempotency key.
KEPT_HEADERS = ("user-agent", "x-event-type", "x-github-event", "x-request-id")
IDEMPOTENCY_HEADER = "idempotency-key"


class WebhookKind(LiveKind):
    key = "webhook"
    label = "Webhook"
    family = "webhook"
    description = "An address a partner's system posts events to, as they happen."
    guarantee = "at_least_once"
    guarantee_note = "A post with an Idempotency-Key header is recognised if it is sent again, and saved once."
    verified_by = "test_streams.py"

    def test(self, settings: dict[str, Any]) -> Outcome:
        return Outcome(True, "A webhook needs nothing to connect to; its address is shown once it is saved.")

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        return Batch()


def idempotency_position(headers: dict[str, str]) -> str | None:
    for name, value in headers.items():
        if name.lower() == IDEMPOTENCY_HEADER and value.strip():
            from service_extraction.live.base import position_of

            return position_of(f"key:{value.strip()}")
    return None
