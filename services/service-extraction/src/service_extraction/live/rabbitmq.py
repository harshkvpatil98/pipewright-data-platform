"""RabbitMQ queues (D1, roadmap Phase 20).

Messages are taken from a queue with manual acknowledgement and
acknowledged only once they are saved; if Pipewright stops in between, the
broker hands them out again. A message that carries a `message_id` property
is recognised on its second delivery and skipped. One without an id cannot
be told apart from a new one, so a redelivery after a crash can be saved
twice: at least once, and the source's page says which applies.
"""

from __future__ import annotations

from typing import Any

from service_extraction.live.base import (
    Batch, LiveError, LiveField, LiveKind, Message, Outcome, host_of, position_of, queue_payload,
)

#: Seconds to wait for more messages before the batch counts as caught up.
WAIT_SECONDS = 0.5


class RabbitMqKind(LiveKind):
    key = "rabbitmq"
    label = "RabbitMQ"
    description = "Take messages from a RabbitMQ queue and acknowledge each one once it is saved."
    fields = (
        LiveField("url", "Address", kind="secret", placeholder="amqps://user:password@host:5671/vhost",
                  help="Includes the password, so it is stored encrypted."),
        LiveField("queue", "Queue", help="An existing queue; Pipewright takes messages from it."),
    )
    guarantee = "at_least_once"
    guarantee_note = "A message published with a message_id is recognised when it comes again, and saved once."
    verified_by = "test_live_queues.py"
    driver_module = "pika"
    driver_package = "pika"

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        return [h for h in (host_of(settings.get("url"), default_scheme="amqp"),) if h]

    def _connect(self, settings: dict[str, Any]):
        import pika

        try:
            parameters = pika.URLParameters(settings["url"])
            parameters.socket_timeout = 10
            parameters.blocked_connection_timeout = 20
            return pika.BlockingConnection(parameters)
        except Exception as exc:  # noqa: BLE001 - the broker's own words are the answer
            raise LiveError(f"Could not reach RabbitMQ: {str(exc)[:300] or exc.__class__.__name__}") from exc

    def test(self, settings: dict[str, Any]) -> Outcome:
        import pika

        try:
            connection = self._connect(settings)
        except LiveError as exc:
            return Outcome(False, str(exc))
        try:
            channel = connection.channel()
            declared = channel.queue_declare(queue=settings["queue"], passive=True)
            waiting = declared.method.message_count
        except pika.exceptions.ChannelClosedByBroker as exc:
            return Outcome(False, f"There is no queue {settings['queue']!r} here ({exc.reply_text}).")
        finally:
            if connection.is_open:
                connection.close()
        return Outcome(True, f"Connected. {settings['queue']} has {waiting:,} messages waiting.")

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        import pika

        connection = self._connect(settings)
        messages: list[Message] = []
        last_tag: int | None = None
        try:
            channel = connection.channel()
            channel.basic_qos(prefetch_count=min(limit, 1000))
            for method, properties, body in channel.consume(settings["queue"], inactivity_timeout=WAIT_SECONDS):
                if method is None:
                    break
                last_tag = method.delivery_tag
                identifier = properties.message_id if properties else None
                messages.append(Message(
                    "message",
                    queue_payload(value=body, key=method.routing_key or None,
                                  headers=dict(properties.headers or {}) if properties and properties.headers else None,
                                  published_at=_stamp(properties), message_id=identifier,
                                  redelivered=bool(method.redelivered) or None),
                    position=position_of(f"id:{identifier}") if identifier else None,
                ))
                if len(messages) >= limit:
                    break
            waiting = channel.queue_declare(queue=settings["queue"], passive=True).method.message_count
        except pika.exceptions.ChannelClosedByBroker as exc:
            connection.close()
            raise LiveError(f"RabbitMQ closed the channel: {exc.reply_text}") from exc
        except Exception:
            if connection.is_open:
                connection.close()
            raise

        def acknowledge() -> None:
            try:
                if last_tag is not None:
                    channel.basic_ack(delivery_tag=last_tag, multiple=True)
            finally:
                if connection.is_open:
                    connection.close()

        def hand_back() -> None:
            try:
                if last_tag is not None:
                    channel.basic_nack(delivery_tag=last_tag, multiple=True, requeue=True)
            finally:
                if connection.is_open:
                    connection.close()

        return Batch(messages=messages, after_commit=acknowledge, abandon=hand_back,
                     more=bool(messages) and (len(messages) >= limit or waiting > 0), behind=waiting)


def _stamp(properties) -> Any:
    from datetime import UTC, datetime

    if properties is None or not properties.timestamp:
        return None
    return datetime.fromtimestamp(int(properties.timestamp), tz=UTC)
