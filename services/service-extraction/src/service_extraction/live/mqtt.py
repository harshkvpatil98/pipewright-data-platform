"""MQTT topics, through a persistent session (D1, roadmap Phase 20).

MQTT keeps nothing for a reader that is not connected unless the reader has
a persistent session: Pipewright connects with its own client id and
`clean_session` off, subscribes at QoS 1, and the broker queues what arrives
in between. Messages are acknowledged only once they are saved, so the
broker sends one again if Pipewright stops in between; MQTT gives a message
no id that survives that, so a repeat cannot be recognised and can be saved
twice: at least once.

The first read makes the session and subscribes; only messages published
after that are kept for it.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from service_extraction.live.base import (
    Batch, LiveError, LiveField, LiveKind, Message, Outcome, host_of, queue_payload,
)

#: Seconds to wait after the last message before the batch counts as caught up.
QUIET_SECONDS = 0.8
CONNECT_SECONDS = 10.0


class MqttKind(LiveKind):
    key = "mqtt"
    label = "MQTT"
    description = "Collect messages on MQTT topics through a session the broker keeps while Pipewright is away."
    fields = (
        LiveField("host", "Broker", placeholder="mqtt.internal"),
        LiveField("port", "Port", kind="number", required=False, default=1883),
        LiveField("topic", "Topic", placeholder="sensors/+/temperature", help="Wildcards + and # are allowed."),
        LiveField("username", "Username", required=False),
        LiveField("password", "Password", kind="secret", required=False),
        LiveField("tls", "Encrypted (TLS)", kind="boolean", required=False, default=False),
    )
    guarantee = "at_least_once"
    guarantee_note = "MQTT gives no message an id, so a message sent again cannot be told from a new one."
    verified_by = "test_live_queues.py"
    driver_module = "paho.mqtt.client"
    driver_package = "paho-mqtt"

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        return [h for h in (host_of(settings.get("host")),) if h]

    def _client(self, settings: dict[str, Any]):
        import paho.mqtt.client as mqtt

        client_id = f"pipewright-{settings.get('source_id') or 'test'}"
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=False,
                             protocol=mqtt.MQTTv311, manual_ack=True)
        if settings.get("username"):
            client.username_pw_set(settings["username"], settings.get("password") or None)
        if settings.get("tls"):
            client.tls_set()
        return client

    def _connect(self, client, settings: dict[str, Any]) -> bool:
        """Connect and wait for the broker's answer. Returns whether it kept a session."""
        ready = threading.Event()
        state: dict[str, Any] = {}

        def on_connect(_client, _userdata, flags, reason, _properties) -> None:
            state["reason"] = reason
            state["present"] = bool(getattr(flags, "session_present", False))
            ready.set()

        client.on_connect = on_connect
        try:
            client.connect(settings["host"], int(settings.get("port") or 1883), keepalive=30)
        except Exception as exc:  # noqa: BLE001 - the network's own words are the answer
            raise LiveError(f"Could not reach the broker: {exc}") from exc
        client.loop_start()
        if not ready.wait(CONNECT_SECONDS):
            client.loop_stop()
            raise LiveError("The broker did not answer in time.")
        reason = state["reason"]
        if getattr(reason, "is_failure", False):
            client.loop_stop()
            raise LiveError(f"The broker refused the connection: {reason}.")
        return state["present"]

    def test(self, settings: dict[str, Any]) -> Outcome:
        client = self._client({**settings, "source_id": "test-connection"})
        try:
            self._connect(client, settings)
        except LiveError as exc:
            return Outcome(False, str(exc))
        finally:
            client.disconnect()
            client.loop_stop()
        return Outcome(True, "Connected. The broker keeps what arrives for Pipewright between reads once the source is saved.")

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        client = self._client(settings)
        received: list[Any] = []
        lock = threading.Lock()
        last_arrival = [time.monotonic()]

        def on_message(_client, _userdata, message) -> None:
            with lock:
                received.append(message)
                last_arrival[0] = time.monotonic()

        client.on_message = on_message
        present = self._connect(client, settings)
        subscribed = bool((cursor or {}).get("subscribed"))
        if not present or not subscribed:
            result, _ = client.subscribe(settings["topic"], qos=1)
            if result != 0:
                client.disconnect()
                client.loop_stop()
                raise LiveError(f"The broker refused the subscription to {settings['topic']}.")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            time.sleep(0.1)
            with lock:
                if len(received) >= limit or time.monotonic() - last_arrival[0] > QUIET_SECONDS:
                    break
        with lock:
            taken = received[:limit]
        messages = [
            Message("message", queue_payload(value=item.payload, topic=item.topic, qos=item.qos,
                                             repeated=bool(item.dup) or None))
            for item in taken
        ]

        def finish(acknowledge: bool) -> None:
            try:
                if acknowledge:
                    for item in taken:
                        if item.qos > 0:
                            client.ack(item.mid, item.qos)
                    time.sleep(0.2)  # let the acknowledgements leave before the connection closes
            finally:
                client.disconnect()
                client.loop_stop()

        # A broker sends only so many messages before they are acknowledged (Mosquitto: 20), so
        # any message at all means there may be more behind it.
        return Batch(messages=messages, cursor={"subscribed": True},
                     after_commit=lambda: finish(True), abandon=lambda: finish(False),
                     more=bool(messages))
