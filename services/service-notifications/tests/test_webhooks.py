"""Signed webhooks (adoption-readiness A8, Y1), against a real local receiver."""

from __future__ import annotations

import json
import os
import socketserver
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_notifications.external_dispatch import dispatch_external_notifications
from service_notifications.models import ExternalNotificationTarget, WebhookDelivery
from service_notifications.senders import webhook_sender
from service_notifications.target_schemas import ExternalNotificationTargetCreate
from service_notifications.targets_service import (
    create_target,
    list_targets,
    list_webhook_deliveries,
    rotate_webhook_secret,
    send_notification_target_test,
)
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from shared_python.db import Base
from shared_python.errors import BadRequestError


class _Server(HTTPServer):
    def server_bind(self):  # no reverse-DNS lookup of the loopback address
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]


@pytest.fixture()
def receiver() -> Iterator[dict]:
    state: dict = {"received": [], "answers": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the http.server name
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["received"].append({"headers": dict(self.headers), "body": body})
            code = state["answers"].pop(0) if state["answers"] else 204
            self.send_response(code)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = _Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/hooks/pipewright"
    previous = os.environ.get("OUTBOUND_ALLOW_LOOPBACK")
    os.environ["OUTBOUND_ALLOW_LOOPBACK"] = "true"
    try:
        yield state
    finally:
        server.shutdown()
        if previous is None:
            os.environ.pop("OUTBOUND_ALLOW_LOOPBACK", None)
        else:
            os.environ["OUTBOUND_ALLOW_LOOPBACK"] = previous


@pytest.fixture()
def world() -> Iterator[dict]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    try:
        yield {"db": db, "user": user, "project": project}
    finally:
        db.close()
        engine.dispose()


def _webhook(world, url: str):
    return create_target(
        world["db"], project_id=world["project"].id, current_user=world["user"],
        payload=ExternalNotificationTargetCreate(
            name="Partner", target_type="webhook", config_json={"url": url},
            subscribed_event_types=["workflow_run_failed"],
        ),
    )


def test_the_secret_is_shown_once_and_kept_encrypted(world, receiver) -> None:
    made = _webhook(world, receiver["url"])
    assert made.signing_secret and made.signing_secret.startswith("whsec_")
    listed = list_targets(world["db"], project_id=world["project"].id, current_user=world["user"]).items[0]
    assert listed.signing_secret is None
    assert listed.config_json["signing_secret_hint"].endswith(made.signing_secret[-4:])
    stored = world["db"].get(ExternalNotificationTarget, made.id).config_json["signing_secret"]
    assert made.signing_secret not in json.dumps(stored), "never stored in the clear"


def test_an_event_arrives_signed_and_is_recorded(world, receiver) -> None:
    made = _webhook(world, receiver["url"])
    dispatch_external_notifications(
        world["db"], project_id=world["project"].id, event_type="workflow_run_failed",
        title="Workflow failed", message="Nightly load failed at Deliver.", level="error",
    )
    [request] = receiver["received"]
    headers = {key.lower(): value for key, value in request["headers"].items()}
    assert webhook_sender.verify(made.signing_secret, headers["pipewright-signature"], request["body"])
    event = json.loads(request["body"])
    assert event["type"] == "workflow_run_failed" and event["project"]["name"] == "Shop"
    assert event["id"] == headers["pipewright-delivery"]

    [delivery] = list_webhook_deliveries(
        world["db"], project_id=world["project"].id, target_id=made.id, current_user=world["user"]
    ).items
    assert (delivery.status, delivery.attempts, delivery.last_status_code) == ("succeeded", 1, 204)


def test_a_signature_is_refused_when_tampered_stale_or_from_another_secret() -> None:
    body = b'{"type":"test"}'
    header = webhook_sender.signature_header("whsec_one", body, now=1_000_000)
    assert webhook_sender.verify("whsec_one", header, body, now=1_000_100)
    assert not webhook_sender.verify("whsec_one", header, body + b" ", now=1_000_100)
    assert not webhook_sender.verify("whsec_one", header, body, now=1_000_000 + 301)
    assert not webhook_sender.verify("whsec_two", header, body, now=1_000_100)
    assert not webhook_sender.verify("whsec_one", "garbage", body)


def test_a_server_error_is_tried_again_and_then_given_up(world, receiver) -> None:
    made = _webhook(world, receiver["url"])
    receiver["answers"] = [503, 503, 503]
    send_notification_target_test(world["db"], project_id=world["project"].id, target_id=made.id, current_user=world["user"])
    db = world["db"]
    delivery = db.query(WebhookDelivery).one()
    assert (delivery.status, delivery.attempts) == ("pending", 1)

    for _ in range(2):
        webhook_sender.retry_due(db, now=datetime.now(UTC) + timedelta(hours=1))
    db.refresh(delivery)
    assert (delivery.status, delivery.attempts, delivery.last_status_code) == ("failed", 3, 503)
    bodies = {request["body"] for request in receiver["received"]}
    assert len(receiver["received"]) == 3 and len(bodies) == 1, "a retry sends the same event"


def test_a_refusal_is_not_repeated(world, receiver) -> None:
    made = _webhook(world, receiver["url"])
    receiver["answers"] = [400]
    answer = send_notification_target_test(
        world["db"], project_id=world["project"].id, target_id=made.id, current_user=world["user"]
    )
    assert not answer.success and "answered 400" in answer.message
    assert world["db"].query(WebhookDelivery).one().status == "failed"


def test_rotating_the_secret_retires_the_old_one(world, receiver) -> None:
    made = _webhook(world, receiver["url"])
    rotated = rotate_webhook_secret(world["db"], project_id=world["project"].id, target_id=made.id, current_user=world["user"])
    assert rotated.signing_secret and rotated.signing_secret != made.signing_secret
    send_notification_target_test(world["db"], project_id=world["project"].id, target_id=made.id, current_user=world["user"])
    request = receiver["received"][-1]
    header = {key.lower(): value for key, value in request["headers"].items()}["pipewright-signature"]
    assert webhook_sender.verify(rotated.signing_secret, header, request["body"])
    assert not webhook_sender.verify(made.signing_secret, header, request["body"])


@pytest.mark.parametrize("url", [
    "http://partner.example.com/hook",  # not https
    "https://169.254.169.254/latest/meta-data",  # the cloud metadata service
])
def test_an_address_that_must_not_receive_events_is_refused(world, url) -> None:
    with pytest.raises(BadRequestError):
        _webhook(world, url)
