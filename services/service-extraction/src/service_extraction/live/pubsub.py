"""Google Cloud Pub/Sub, pulled over its REST API (D1, roadmap Phase 20).

Messages are pulled from a subscription and acknowledged only after they
are saved. A message Pub/Sub delivers again (because Pipewright stopped
before acknowledging, or the acknowledgement deadline passed) carries the
same message id, which is its position, so it is recognised and skipped:
each message is saved once, by its id.

Signing in uses a service account key: a JWT signed with its private key is
exchanged for an access token (RFC 7523), the same as Google's own client
libraries do, without gRPC. With an emulator address set (the Pub/Sub
emulator, which the tests run against) no sign-in is needed.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from service_extraction.live.base import (
    Batch, LiveError, LiveField, LiveKind, Message, Outcome, host_of, queue_payload,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/pubsub"
API = "https://pubsub.googleapis.com"
#: Seconds a pull may wait for messages before the read counts it as empty.
PULL_WAIT = 5.0

#: Access tokens by key id, until shortly before they expire.
_TOKENS: dict[str, tuple[str, float]] = {}


def access_token(service_account: dict[str, Any], *, client: httpx.Client) -> str:
    import jwt

    key_id = str(service_account.get("private_key_id") or service_account.get("client_email"))
    cached = _TOKENS.get(key_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    now = int(time.time())
    assertion = jwt.encode(
        {"iss": service_account["client_email"], "scope": SCOPE, "aud": service_account.get("token_uri") or TOKEN_URL,
         "iat": now, "exp": now + 3600},
        service_account["private_key"], algorithm="RS256",
        headers={"kid": service_account.get("private_key_id")} if service_account.get("private_key_id") else None,
    )
    response = client.post(service_account.get("token_uri") or TOKEN_URL, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    if response.status_code != 200:
        raise LiveError(f"Google refused the service account key: {response.text[:200]}")
    body = response.json()
    _TOKENS[key_id] = (body["access_token"], now + int(body.get("expires_in", 3600)))
    return body["access_token"]


class PubSubKind(LiveKind):
    key = "pubsub"
    label = "Google Pub/Sub"
    description = "Pull a Pub/Sub subscription and acknowledge each message once it is saved."
    fields = (
        LiveField("project", "Project id"),
        LiveField("subscription", "Subscription", help="The subscription's id, not the topic's."),
        LiveField("service_account_json", "Service account key", kind="text", required=False,
                  help="The whole key file. Needs the Pub/Sub Subscriber role. Stored encrypted."),
        LiveField("emulator_host", "Emulator address", required=False,
                  help="Only for Google's Pub/Sub emulator, for example localhost:8085."),
    )
    guarantee = "message_id"
    guarantee_note = "Pub/Sub delivers a message again until it is acknowledged; its message id is how a repeat is known."
    verified_by = "test_live_queues.py"

    @property
    def secret_fields(self) -> tuple[str, ...]:
        return ("service_account_json",)

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        return [h for h in (host_of(settings.get("emulator_host"), default_scheme="http"),) if h]

    def _session(self, settings: dict[str, Any]) -> tuple[httpx.Client, str, dict[str, str]]:
        client = httpx.Client(timeout=20)
        emulator = (settings.get("emulator_host") or "").strip()
        if emulator:
            base = emulator if emulator.startswith("http") else f"http://{emulator}"
            return client, base.rstrip("/"), {}
        raw = settings.get("service_account_json")
        if not raw:
            client.close()
            raise LiveError("A service account key is needed to read from Pub/Sub.")
        try:
            account = json.loads(raw) if isinstance(raw, str) else dict(raw)
            token = access_token(account, client=client)
        except (json.JSONDecodeError, KeyError) as exc:
            client.close()
            raise LiveError("The service account key is not a Google key file (it needs client_email and private_key).") from exc
        return client, API, {"Authorization": f"Bearer {token}"}

    def _path(self, settings: dict[str, Any]) -> str:
        return f"/v1/projects/{settings['project']}/subscriptions/{settings['subscription']}"

    def test(self, settings: dict[str, Any]) -> Outcome:
        try:
            client, base, headers = self._session(settings)
        except LiveError as exc:
            return Outcome(False, str(exc))
        try:
            response = client.get(base + self._path(settings), headers=headers)
        except httpx.HTTPError as exc:
            return Outcome(False, f"Could not reach Pub/Sub: {exc}")
        finally:
            client.close()
        if response.status_code == 404:
            return Outcome(False, f"There is no subscription {settings['subscription']} in {settings['project']}.")
        if response.status_code >= 400:
            return Outcome(False, f"Pub/Sub refused: {response.text[:200]}")
        topic = response.json().get("topic", "").rsplit("/", 1)[-1]
        return Outcome(True, f"Connected. The subscription reads the topic {topic}.")

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        client, base, headers = self._session(settings)
        path = base + self._path(settings)
        messages: list[Message] = []
        ack_ids: list[str] = []
        try:
            while len(messages) < limit:
                # A pull with nothing waiting is held open until something arrives; ask for an
                # answer now (the emulator honours it) and treat a held pull as an empty one.
                try:
                    response = client.post(f"{path}:pull", headers=headers, timeout=httpx.Timeout(20, read=PULL_WAIT),
                                           json={"maxMessages": min(1000, limit - len(messages)),
                                                 "returnImmediately": True})
                except httpx.ReadTimeout:
                    break
                if response.status_code >= 400:
                    raise LiveError(f"Pulling from Pub/Sub failed: {response.text[:200]}")
                received = response.json().get("receivedMessages") or []
                if not received:
                    break
                for item in received:
                    message = item.get("message") or {}
                    data = base64.b64decode(message["data"]) if message.get("data") else b""
                    messages.append(Message(
                        "message",
                        queue_payload(value=data, key=message.get("orderingKey") or None,
                                      headers=message.get("attributes") or None,
                                      published_at=message.get("publishTime"), message_id=message.get("messageId")),
                        position=message.get("messageId"),
                    ))
                    ack_ids.append(item["ackId"])
        except Exception:
            client.close()
            raise

        def acknowledge() -> None:
            try:
                for start in range(0, len(ack_ids), 1000):
                    response = client.post(f"{path}:acknowledge", headers=headers, json={"ackIds": ack_ids[start:start + 1000]})
                    if response.status_code >= 400:
                        raise LiveError(f"Acknowledging the saved messages failed: {response.text[:200]}")
            finally:
                client.close()

        def let_go() -> None:
            # Not saved: hand them back now rather than at the deadline.
            try:
                if ack_ids:
                    client.post(f"{path}:modifyAckDeadline", headers=headers,
                                json={"ackIds": ack_ids, "ackDeadlineSeconds": 0})
            finally:
                client.close()

        return Batch(messages=messages, after_commit=acknowledge, abandon=let_go, more=len(messages) >= limit)
