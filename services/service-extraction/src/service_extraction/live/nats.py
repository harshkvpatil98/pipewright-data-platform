"""NATS JetStream streams (D1, roadmap Phase 20).

Every message in a JetStream stream has a sequence number. Pipewright saves
the last one it stored, with the events, and each read opens a short-lived
consumer starting just after it (no durable consumer left on the server,
nothing to acknowledge), so a restart carries on exactly there and each
message is saved once. Starting "from now" takes the stream's last sequence
on the first read.

Plain NATS subjects without JetStream keep nothing for a reader that is not
connected, so they cannot be followed in micro-batches; the test says so.
"""

from __future__ import annotations

import asyncio
from typing import Any

from service_extraction.live.base import (
    Batch, LiveError, LiveField, LiveKind, Message, Outcome, host_of, queue_payload,
)

#: Seconds a fetch waits for messages before the batch counts as caught up.
WAIT_SECONDS = 1.0


def _run(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    raise RuntimeError("NATS reads run outside an event loop")  # pragma: no cover - the runner is synchronous


class NatsKind(LiveKind):
    key = "nats"
    label = "NATS JetStream"
    description = "Read a JetStream stream from the message after the last one Pipewright saved."
    fields = (
        LiveField("servers", "Servers", placeholder="nats://nats-1:4222,nats://nats-2:4222"),
        LiveField("stream", "Stream"),
        LiveField("subject", "Subject", required=False, help="Only messages on this subject (wildcards allowed)."),
        LiveField("username", "Username", required=False),
        LiveField("password", "Password", kind="secret", required=False),
        LiveField("token", "Token", kind="secret", required=False),
        LiveField("start_from", "Start from", kind="select", required=False, default="earliest",
                  options=("earliest", "latest"),
                  help="The first time only: every message kept, or only those that arrive from now."),
    )
    guarantee = "position"
    guarantee_note = "The stream sequence of the last message is saved with the events."
    verified_by = "test_live_queues.py"
    driver_module = "nats"
    driver_package = "nats-py"

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        return [h for h in (host_of(a) for a in str(settings.get("servers") or "").split(",")) if h]

    async def _connect(self, settings: dict[str, Any]):
        import nats

        options: dict[str, Any] = {"connect_timeout": 5, "max_reconnect_attempts": 0, "allow_reconnect": False}
        if settings.get("username"):
            options.update(user=settings["username"], password=settings.get("password") or "")
        if settings.get("token"):
            options["token"] = settings["token"]
        servers = [s.strip() for s in str(settings["servers"]).split(",") if s.strip()]
        try:
            return await nats.connect(servers, **options)
        except Exception as exc:  # noqa: BLE001 - the server's own words are the answer
            raise LiveError(f"Could not reach NATS: {str(exc)[:300] or exc.__class__.__name__}") from exc

    def test(self, settings: dict[str, Any]) -> Outcome:
        async def check() -> Outcome:
            from nats.js.errors import NotFoundError, ServiceUnavailableError

            client = await self._connect(settings)
            try:
                info = await client.jetstream().stream_info(settings["stream"])
            except ServiceUnavailableError:
                return Outcome(False, "JetStream is not on for this server, and plain subjects keep nothing to read later.")
            except NotFoundError:
                return Outcome(False, f"There is no stream {settings['stream']!r} on this server.")
            finally:
                await client.close()
            return Outcome(True, f"Connected. {settings['stream']} keeps {info.state.messages:,} messages "
                                 f"on {', '.join(info.config.subjects or [])}.")

        try:
            return _run(check())
        except LiveError as exc:
            return Outcome(False, str(exc))

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        return _run(self._read(settings, dict(cursor or {}), limit))

    async def _read(self, settings: dict[str, Any], cursor: dict[str, Any], limit: int) -> Batch:
        from nats.errors import TimeoutError as FetchTimeout
        from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
        from nats.js.errors import NotFoundError

        client = await self._connect(settings)
        messages: list[Message] = []
        try:
            js = client.jetstream()
            try:
                info = await js.stream_info(settings["stream"])
            except NotFoundError as exc:
                raise LiveError(f"There is no stream {settings['stream']!r} on this server.") from exc
            last = info.state.last_seq
            if "seq" not in cursor:
                cursor["seq"] = last if (settings.get("start_from") or "earliest") == "latest" else 0
            after = int(cursor["seq"])
            if after < last:
                subject = settings.get("subject") or (info.config.subjects[0] if len(info.config.subjects or []) == 1 else ">")
                subscription = await js.pull_subscribe(
                    subject, stream=settings["stream"],
                    config=ConsumerConfig(deliver_policy=DeliverPolicy.BY_START_SEQUENCE, opt_start_seq=after + 1,
                                          ack_policy=AckPolicy.NONE, inactive_threshold=30.0),
                )
                try:
                    while len(messages) < limit:
                        try:
                            batch = await subscription.fetch(batch=min(500, limit - len(messages)), timeout=WAIT_SECONDS)
                        except FetchTimeout:
                            break
                        for item in batch:
                            sequence = item.metadata.sequence.stream
                            messages.append(Message(
                                "message",
                                queue_payload(value=item.data, headers=dict(item.headers or {}) or None,
                                              published_at=item.metadata.timestamp, subject=item.subject, sequence=sequence),
                                position=f"seq:{sequence}",
                            ))
                            cursor["seq"] = max(int(cursor["seq"]), int(sequence))
                finally:
                    await subscription.unsubscribe()
        finally:
            await client.close()
        return Batch(messages=messages, cursor=cursor, more=int(cursor["seq"]) < last and len(messages) >= limit,
                     behind=max(0, last - int(cursor["seq"])))
