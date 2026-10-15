"""Live sources: webhooks, change capture and message queues (D1, roadmap Phase 20).

`KINDS` is the one list of what can be followed. Each kind is a class in its
own module with the surface `base.LiveKind` describes; nothing outside this
package knows what a binary log or a partition is.
"""

from __future__ import annotations

from service_extraction.live.base import LiveError, LiveKind
from service_extraction.live.kafka import EventHubsKind, KafkaKind
from service_extraction.live.kinesis import KinesisKind
from service_extraction.live.mongodb import MongoChangeCapture
from service_extraction.live.mqtt import MqttKind
from service_extraction.live.mysql import MySqlChangeCapture
from service_extraction.live.nats import NatsKind
from service_extraction.live.postgres import PostgresChangeCapture
from service_extraction.live.pubsub import PubSubKind
from service_extraction.live.pulsar import PulsarKind
from service_extraction.live.rabbitmq import RabbitMqKind
from service_extraction.live.sqlserver import SqlServerChangeCapture
from service_extraction.live.webhook import WebhookKind

KINDS: dict[str, LiveKind] = {
    kind.key: kind
    for kind in (
        WebhookKind(),
        PostgresChangeCapture(),
        MySqlChangeCapture(),
        MongoChangeCapture(),
        SqlServerChangeCapture(),
        KafkaKind(),
        EventHubsKind(),
        KinesisKind(),
        PubSubKind(),
        PulsarKind(),
        RabbitMqKind(),
        NatsKind(),
        MqttKind(),
    )
}


def get_kind(key: str) -> LiveKind:
    kind = KINDS.get(key)
    if kind is None:
        raise LiveError(f"There is no live feed of kind {key!r}. Known: {', '.join(KINDS)}.")
    return kind


__all__ = ["KINDS", "LiveError", "LiveKind", "get_kind"]
