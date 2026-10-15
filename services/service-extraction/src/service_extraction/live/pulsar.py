"""Apache Pulsar, read with a reader from a saved message id (D1, roadmap Phase 20).

A reader needs no subscription on the broker: Pipewright keeps the last
message id it saved, with the events, and opens a reader just after it, so a
restart carries on exactly there and each message is saved once. A
partitioned topic is read partition by partition, each with its own id.
Starting "from now" saves the moment of the first read and, until a message
has been saved, reads from that time.
"""

from __future__ import annotations

import base64
import time
from typing import Any

from service_extraction.live.base import (
    Batch, LiveError, LiveField, LiveKind, Message, Outcome, epoch_ms, host_of, position_of, queue_payload,
)

#: How long a reader waits for the next message before the batch counts as caught up.
WAIT_MS = 300


class PulsarKind(LiveKind):
    key = "pulsar"
    label = "Apache Pulsar"
    description = "Read a Pulsar topic from where Pipewright last stopped, without a subscription."
    fields = (
        LiveField("service_url", "Service URL", placeholder="pulsar://broker:6650",
                  help="pulsar:// or pulsar+ssl://"),
        LiveField("topic", "Topic", placeholder="persistent://public/default/orders"),
        LiveField("token", "Token", kind="secret", required=False, help="For a cluster that signs in with tokens."),
        LiveField("start_from", "Start from", kind="select", required=False, default="earliest",
                  options=("earliest", "latest"),
                  help="The first time only: every message kept, or only those that arrive from now."),
    )
    guarantee = "position"
    guarantee_note = "The last message id is saved with the events."
    verified_by = "test_live_queues.py"
    driver_module = "pulsar"
    driver_package = "pulsar-client"

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        return [h for h in (host_of(settings.get("service_url")),) if h]

    def _client(self, settings: dict[str, Any]):
        import pulsar

        options: dict[str, Any] = {"operation_timeout_seconds": 15, "connection_timeout_ms": 10000}
        if settings.get("token"):
            options["authentication"] = pulsar.AuthenticationToken(settings["token"])
        try:
            return pulsar.Client(settings["service_url"], logger=_quiet(), **options)
        except Exception as exc:  # noqa: BLE001 - a bad URL raises here
            raise LiveError(f"The service URL was refused: {exc}") from exc

    def test(self, settings: dict[str, Any]) -> Outcome:
        try:
            client = self._client(settings)
        except LiveError as exc:
            return Outcome(False, str(exc))
        try:
            partitions = client.get_topic_partitions(settings["topic"])
        except Exception as exc:  # noqa: BLE001 - the broker's own words are the answer
            return Outcome(False, f"Could not reach the topic: {str(exc)[:300]}")
        finally:
            client.close()
        many = len(partitions) > 1
        return Outcome(True, f"Connected. {settings['topic']} has {len(partitions)} partitions." if many
                       else f"Connected to {settings['topic']}.")

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        import pulsar

        cursor = dict(cursor or {})
        saved: dict[str, str] = dict(cursor.get("ids") or {})
        since = cursor.get("since")
        if not saved and since is None and (settings.get("start_from") or "earliest") == "latest":
            since = int(time.time() * 1000)
        client = self._client(settings)
        messages: list[Message] = []
        more = False
        try:
            try:
                partitions = client.get_topic_partitions(settings["topic"])
            except Exception as exc:  # noqa: BLE001
                raise LiveError(f"Could not reach the topic: {str(exc)[:300]}") from exc
            for partition in partitions:
                if len(messages) >= limit:
                    more = True
                    break
                start = (pulsar.MessageId.deserialize(base64.b64decode(saved[partition])) if partition in saved
                         else pulsar.MessageId.earliest)
                reader = client.create_reader(partition, start, start_message_id_inclusive=False)
                try:
                    if partition not in saved and since is not None:
                        reader.seek(int(since))
                    while len(messages) < limit:
                        try:
                            item = reader.read_next(timeout_millis=WAIT_MS)
                        except pulsar.Timeout:
                            break
                        identifier = base64.b64encode(item.message_id().serialize()).decode()
                        messages.append(Message(
                            "message",
                            queue_payload(value=item.data(), key=item.partition_key() or None,
                                          headers=dict(item.properties() or {}) or None,
                                          published_at=epoch_ms(item.publish_timestamp()), topic=partition),
                            position=position_of(f"{partition}#{identifier}"),
                        ))
                        saved[partition] = identifier
                    else:
                        more = True
                finally:
                    reader.close()
        finally:
            client.close()
        out: dict[str, Any] = {"ids": saved}
        if since is not None and len(saved) < len(partitions):
            out["since"] = since
        return Batch(messages=messages, cursor=out, more=more)


def _quiet():
    import logging

    logger = logging.getLogger("service_extraction.live.pulsar.client")
    logger.setLevel(logging.ERROR)
    return logger
