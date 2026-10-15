"""Kafka, and Azure Event Hubs through its Kafka endpoint (D1, roadmap Phase 20).

Pipewright keeps each partition's next offset itself, saved with the events,
and assigns the partitions directly from those offsets rather than joining a
consumer group: a restart reads from exactly where the saved events end, so
each message is saved once, and no group rebalancing can move a partition
underneath a batch. Starting "from now" resolves to the partitions' current
ends on the first read and saves them, so nothing that arrives between
reads is skipped.

Event Hubs speaks Kafka on port 9093 with SASL PLAIN, the user
`$ConnectionString` and the connection string as the password. Microsoft's
emulator asks for plain SASL on port 9092 with `UseDevelopmentEmulator=true`
in the connection string, which is what the tests run against.
"""

from __future__ import annotations

import re
from typing import Any

from service_extraction.live.base import (
    Batch, LiveError, LiveField, LiveKind, Message, Outcome, epoch_ms, host_of, queue_payload,
)

_START = ("earliest", "latest")


def _client_config(settings: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {
        "bootstrap.servers": settings["bootstrap_servers"],
        "socket.timeout.ms": 10000,
        "session.timeout.ms": 10000,
        "enable.auto.commit": False,
        "enable.partition.eof": True,
        "group.id": f"pipewright-{settings.get('source_id') or 'test'}",
        "client.id": "pipewright",
        "logger": _quiet_logger(),
    }
    protocol = settings.get("security_protocol") or "PLAINTEXT"
    config["security.protocol"] = protocol
    if protocol.startswith("SASL"):
        config["sasl.mechanisms"] = settings.get("sasl_mechanism") or "PLAIN"
        config["sasl.username"] = settings.get("username") or ""
        config["sasl.password"] = settings.get("password") or ""
    return config


def _quiet_logger():
    import logging

    logger = logging.getLogger("service_extraction.live.kafka.client")
    logger.setLevel(logging.ERROR)
    return logger


class KafkaReader:
    """The read both Kafka and Event Hubs do, given the client settings."""

    def partitions(self, consumer, topic: str) -> list[int]:
        metadata = consumer.list_topics(topic, timeout=10)
        found = metadata.topics.get(topic)
        if found is None or found.error is not None:
            reason = f" ({found.error.str()})" if found is not None and found.error is not None else ""
            raise LiveError(f"There is no topic {topic!r} on this server{reason}.")
        return sorted(found.partitions)

    def test(self, settings: dict[str, Any], label: str) -> Outcome:
        from confluent_kafka import Consumer, KafkaException, TopicPartition

        try:
            consumer = Consumer(_client_config(settings))
        except KafkaException as exc:
            return Outcome(False, f"The settings were refused: {exc}")
        try:
            partitions = self.partitions(consumer, settings["topic"])
            waiting = 0
            for partition in partitions:
                low, high = consumer.get_watermark_offsets(TopicPartition(settings["topic"], partition), timeout=10)
                waiting += max(0, high - low)
        except LiveError as exc:
            return Outcome(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - the broker's own words are the answer
            return Outcome(False, f"Could not reach {label}: {str(exc)[:300]}")
        finally:
            consumer.close()
        return Outcome(True, f"Connected. {settings['topic']} has {len(partitions)} partitions and "
                             f"{waiting:,} messages kept.")

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        from confluent_kafka import OFFSET_BEGINNING, Consumer, KafkaError, TopicPartition

        topic = settings["topic"]
        offsets = {int(p): int(o) for p, o in ((cursor or {}).get("partitions") or {}).items()}
        consumer = Consumer(_client_config(settings))
        messages: list[Message] = []
        try:
            partitions = self.partitions(consumer, topic)
            assignment = []
            ends: dict[int, int] = {}
            for partition in partitions:
                low, high = consumer.get_watermark_offsets(TopicPartition(topic, partition), timeout=10)
                ends[partition] = high
                if partition not in offsets:
                    # First time this partition is seen: the start the source asked for.
                    offsets[partition] = low if (settings.get("start_from") or "earliest") == "earliest" else high
                if offsets[partition] < low:
                    offsets[partition] = low  # kept messages expired before they were read
                if offsets[partition] < high:
                    assignment.append(TopicPartition(topic, partition, offsets[partition]))
            if assignment:
                consumer.assign(assignment)
                finished: set[int] = set()
                live = {tp.partition for tp in assignment}
                while len(messages) < limit and finished != live:
                    batch = consumer.consume(num_messages=min(500, limit - len(messages)), timeout=1.0)
                    if not batch:
                        break
                    for item in batch:
                        error = item.error()
                        if error is not None:
                            if error.code() == KafkaError._PARTITION_EOF:
                                finished.add(item.partition())
                                continue
                            raise LiveError(f"Reading {topic} failed: {error.str()}")
                        partition, offset = item.partition(), item.offset()
                        if offset < offsets.get(partition, OFFSET_BEGINNING):
                            continue
                        _, stamp = item.timestamp()
                        messages.append(Message(
                            "message",
                            queue_payload(value=item.value(), key=item.key(), headers=dict(item.headers() or []),
                                          published_at=epoch_ms(stamp), partition=partition, offset=offset),
                            position=f"{partition}:{offset}",
                        ))
                        offsets[partition] = offset + 1
                        if offset + 1 >= ends.get(partition, 0):
                            finished.add(partition)
                        if len(messages) >= limit:
                            break
            behind = sum(max(0, ends[p] - offsets.get(p, ends[p])) for p in ends)
        finally:
            consumer.close()
        return Batch(messages=messages, cursor={"partitions": {str(p): o for p, o in offsets.items()}},
                     more=behind > 0, behind=behind)


class KafkaKind(LiveKind):
    key = "kafka"
    label = "Kafka"
    description = "Read a Kafka topic, every partition, from where Pipewright last stopped."
    fields = (
        LiveField("bootstrap_servers", "Servers", placeholder="broker-1:9092,broker-2:9092",
                  help="One or more host:port, separated by commas."),
        LiveField("topic", "Topic"),
        LiveField("start_from", "Start from", kind="select", required=False, default="earliest", options=_START,
                  help="The first time only: every message kept, or only those that arrive from now."),
        LiveField("security_protocol", "Security", kind="select", required=False, default="PLAINTEXT",
                  options=("PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL")),
        LiveField("sasl_mechanism", "Sign-in method", kind="select", required=False, default="PLAIN",
                  options=("PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512")),
        LiveField("username", "Username", required=False),
        LiveField("password", "Password", kind="secret", required=False),
    )
    guarantee = "position"
    guarantee_note = "Each partition's offset is saved with the events."
    verified_by = "test_live_queues.py"
    driver_module = "confluent_kafka"
    driver_package = "confluent-kafka"

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        return [h for h in (host_of(a) for a in str(settings.get("bootstrap_servers") or "").split(",")) if h]

    def test(self, settings: dict[str, Any]) -> Outcome:
        return KafkaReader().test(settings, "Kafka")

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        return KafkaReader().read(settings, cursor, limit=limit)


_ENDPOINT = re.compile(r"Endpoint=sb://(?P<host>[^/;:]+)(?::(?P<port>\d+))?/?", re.IGNORECASE)
_ENTITY = re.compile(r"EntityPath=(?P<name>[^;]+)", re.IGNORECASE)


def event_hubs_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """An Event Hubs connection string as the Kafka settings it stands for."""
    connection = str(settings.get("connection_string") or "")
    endpoint = _ENDPOINT.search(connection)
    if endpoint is None:
        raise LiveError("The connection string has no Endpoint=sb://...; copy it from the namespace's "
                        "Shared access policies.")
    emulator = "usedevelopmentemulator=true" in connection.replace(" ", "").lower()
    port = endpoint.group("port") or ("9092" if emulator else "9093")
    entity = _ENTITY.search(connection)
    hub = (settings.get("event_hub") or (entity.group("name") if entity else "")).strip()
    if not hub:
        raise LiveError("Name the event hub, or use a connection string that includes EntityPath.")
    return {
        **settings,
        "bootstrap_servers": f"{endpoint.group('host')}:{port}",
        "topic": hub,
        "security_protocol": "SASL_PLAINTEXT" if emulator else "SASL_SSL",
        "sasl_mechanism": "PLAIN",
        "username": "$ConnectionString",
        "password": connection,
    }


class EventHubsKind(LiveKind):
    key = "event_hubs"
    label = "Azure Event Hubs"
    description = "Read an event hub through its Kafka endpoint, every partition."
    fields = (
        LiveField("connection_string", "Connection string", kind="secret",
                  help="From the namespace's Shared access policies. Includes the key, so it is stored encrypted."),
        LiveField("event_hub", "Event hub", required=False,
                  help="Leave blank when the connection string names it (EntityPath)."),
        LiveField("start_from", "Start from", kind="select", required=False, default="earliest", options=_START),
    )
    guarantee = "position"
    guarantee_note = "Each partition's offset is saved with the events."
    verified_by = "test_live_queues.py"
    driver_module = "confluent_kafka"
    driver_package = "confluent-kafka"

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        try:
            converted = event_hubs_settings(settings)
        except LiveError:
            return []
        return [h for h in (host_of(converted["bootstrap_servers"]),) if h]

    def test(self, settings: dict[str, Any]) -> Outcome:
        try:
            converted = event_hubs_settings(settings)
        except LiveError as exc:
            return Outcome(False, str(exc))
        return KafkaReader().test(converted, "Event Hubs")

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        return KafkaReader().read(event_hubs_settings(settings), cursor, limit=limit)
