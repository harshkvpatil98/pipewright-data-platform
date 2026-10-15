"""Message queues against real servers and the vendors' test servers (D1, L3).

Kafka, Azure Event Hubs (Microsoft's emulator, through its Kafka endpoint),
Amazon Kinesis (a test server for the Kinesis API), Google Pub/Sub (Google's
emulator), Apache Pulsar, RabbitMQ, NATS JetStream and MQTT (Mosquitto), from
`docker-compose.live.yml`. Each test publishes, lets the runner read, and
checks what its guarantee says: kinds that own their position never store a
message twice; kinds that acknowledge recognise a redelivery by its id where
there is one, and say so where there is not. The `live` CI job runs these
with `LIVE_TEST_SERVERS=1`; without it they skip.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_extraction import live_recipes, streams
from service_extraction.live import KINDS
from service_extraction.models import StreamEvent, StreamSource
from service_extraction.schemas import LiveRecipeCreate, StreamSourceCreate
from service_projects.models import Project
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

import live_servers as servers

pytestmark = pytest.mark.skipif(not servers.ENABLED, reason=servers.REASON)

OWNER_ID = uuid.UUID("0a0a0a0a-0a0a-0a0a-0a0a-0a0a0a0a0a0a")
SETTINGS = SimpleNamespace(max_upload_size_bytes=50 * 1024 * 1024, preview_row_limit=50, profile_sample_value_limit=5)


@pytest.fixture(autouse=True)
def _loopback(monkeypatch) -> None:
    """The test servers are on this machine, which the outbound guard refuses by default."""
    monkeypatch.setenv("OUTBOUND_ALLOW_LOOPBACK", "true")


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def storage(tmp_path) -> LocalStorageBackend:
    return LocalStorageBackend(str(tmp_path / "storage"))


@pytest.fixture()
def world(db: Session) -> dict:
    db.add(User(id=OWNER_ID, username="owner", password_hash="x", role="admin", is_active=True))
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.commit()
    now = datetime.now(UTC)
    return {"project": project, "user": UserRead(id=OWNER_ID, username="owner", role="admin", is_active=True,
                                                 created_at=now, updated_at=now)}


def _source(db, world, kind: str, settings: dict, name: str | None = None) -> uuid.UUID:
    tested = streams.test_new_settings(db, world["project"].id, _try(kind, settings), world["user"])
    assert tested.ok, tested.message
    created = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name=name or f"{kind} {uuid.uuid4().hex[:6]}", kind=kind, settings=settings), world["user"])
    return created.id


def _try(kind, settings):
    from service_extraction.schemas import StreamTestRequest

    return StreamTestRequest(kind=kind, settings=settings)


def _pass(db, source_id, storage) -> dict:
    source = db.get(StreamSource, source_id)
    source.next_read_at = None
    source.last_materialised_at = datetime.now(UTC) - timedelta(minutes=10)
    db.commit()
    result = streams.run_pass(db, source_id, owner="test-runner", storage_backend=storage, settings=SETTINGS)
    assert result["error"] is None, result["error"]
    return result


def _values(db, source_id) -> list:
    return [e.payload_json.get("value") for e in db.scalars(
        select(StreamEvent).where(StreamEvent.source_id == source_id).order_by(StreamEvent.seq)).all()]


def _orders(db, source_id) -> list[int]:
    return sorted(v["order"] for v in _values(db, source_id) if isinstance(v, dict) and "order" in v)


def _count(db, source_id) -> int:
    return int(db.scalar(select(func.count()).select_from(StreamEvent).where(StreamEvent.source_id == source_id)))


# ----------------------------------------------------------------------- Kafka


def test_kafka_reads_every_partition_and_never_stores_a_message_twice(db, world, storage):
    from confluent_kafka import Producer
    from confluent_kafka.admin import AdminClient, NewTopic

    topic = f"orders_{uuid.uuid4().hex[:6]}"
    admin = AdminClient({"bootstrap.servers": servers.KAFKA})  # kept: the future needs its client
    admin.create_topics([NewTopic(topic, num_partitions=3)])[topic].result()
    producer = Producer({"bootstrap.servers": servers.KAFKA})
    for i in range(30):
        producer.produce(topic, key=str(i % 5), value=json.dumps({"order": i}), headers={"source": "shop"})
    producer.flush()
    source_id = _source(db, world, "kafka", {"bootstrap_servers": servers.KAFKA, "topic": topic})
    _pass(db, source_id, storage)
    assert _orders(db, source_id) == list(range(30))
    for i in range(30, 35):
        producer.produce(topic, value=json.dumps({"order": i}))
    producer.flush()
    _pass(db, source_id, storage)
    _pass(db, source_id, storage)
    assert _orders(db, source_id) == list(range(35))  # each once
    offsets = streams.cursor_of(db.get(StreamSource, source_id))["partitions"]
    assert sum(offsets.values()) == 35
    log = db.get(Dataset, db.get(StreamSource, source_id).dataset_id)
    assert log.row_count == 35


def test_kafka_from_now_skips_what_was_there_and_nothing_after(db, world, storage):
    from confluent_kafka import Producer

    topic = f"latest_{uuid.uuid4().hex[:6]}"
    producer = Producer({"bootstrap.servers": servers.KAFKA})
    producer.produce(topic, value=json.dumps({"order": -1}))
    producer.flush()
    time.sleep(1)
    source_id = _source(db, world, "kafka", {"bootstrap_servers": servers.KAFKA, "topic": topic, "start_from": "latest"})
    _pass(db, source_id, storage)
    for i in range(3):
        producer.produce(topic, value=json.dumps({"order": i}))
    producer.flush()
    _pass(db, source_id, storage)
    assert _orders(db, source_id) == [0, 1, 2]


# ------------------------------------------------------------------ Event Hubs


def test_event_hubs_is_read_through_its_kafka_endpoint(db, world, storage):
    from confluent_kafka import Producer

    from service_extraction.live.kafka import event_hubs_settings

    settings = {"connection_string": servers.EVENT_HUBS, "event_hub": servers.EVENT_HUB_NAME}
    converted = event_hubs_settings(settings)
    producer = Producer({"bootstrap.servers": converted["bootstrap_servers"], "security.protocol": "SASL_PLAINTEXT",
                         "sasl.mechanisms": "PLAIN", "sasl.username": "$ConnectionString",
                         "sasl.password": servers.EVENT_HUBS})
    marker = uuid.uuid4().hex
    source_id = _source(db, world, "event_hubs", {**settings, "start_from": "latest"})
    _pass(db, source_id, storage)
    for i in range(4):
        producer.produce(servers.EVENT_HUB_NAME, value=json.dumps({"order": i, "marker": marker}))
    producer.flush(15)
    for _ in range(10):
        _pass(db, source_id, storage)
        if len([v for v in _values(db, source_id) if isinstance(v, dict) and v.get("marker") == marker]) == 4:
            break
        time.sleep(1)
    mine = sorted(v["order"] for v in _values(db, source_id) if isinstance(v, dict) and v.get("marker") == marker)
    assert mine == [0, 1, 2, 3]
    assert converted["security_protocol"] == "SASL_PLAINTEXT"  # the emulator; Azure itself is SASL_SSL on 9093
    real = event_hubs_settings({"connection_string": "Endpoint=sb://shop.servicebus.windows.net/;SharedAccessKeyName=k;"
                                                     "SharedAccessKey=s;EntityPath=orders"})
    assert (real["bootstrap_servers"], real["security_protocol"], real["topic"]) == (
        "shop.servicebus.windows.net:9093", "SASL_SSL", "orders")


# ---------------------------------------------------------------------- Kinesis


def test_kinesis_reads_every_shard_from_the_saved_sequence(db, world, storage):
    import boto3

    client = boto3.client("kinesis", endpoint_url=servers.KINESIS, region_name="us-east-1",
                          aws_access_key_id="test", aws_secret_access_key="test")
    stream = f"orders_{uuid.uuid4().hex[:6]}"
    client.create_stream(StreamName=stream, ShardCount=2)
    for _ in range(40):
        if client.describe_stream_summary(StreamName=stream)["StreamDescriptionSummary"]["StreamStatus"] == "ACTIVE":
            break
        time.sleep(0.5)
    for i in range(12):
        client.put_record(StreamName=stream, Data=json.dumps({"order": i}).encode(), PartitionKey=f"k{i}")
    source_id = _source(db, world, "kinesis", {"region": "us-east-1", "stream": stream, "access_key_id": "test",
                                               "secret_access_key": "test", "endpoint_url": servers.KINESIS})
    _pass(db, source_id, storage)
    for i in range(12, 15):
        client.put_record(StreamName=stream, Data=json.dumps({"order": i}).encode(), PartitionKey=f"k{i}")
    _pass(db, source_id, storage)
    _pass(db, source_id, storage)
    assert _orders(db, source_id) == list(range(15))
    assert len(streams.cursor_of(db.get(StreamSource, source_id))["shards"]) == 2


# ---------------------------------------------------------------------- Pub/Sub


def _pubsub_topic(name: str) -> str:
    import httpx

    base = f"{servers.PUBSUB}/v1/projects/{servers.PUBSUB_PROJECT}"
    httpx.put(f"{base}/topics/{name}").raise_for_status()
    httpx.put(f"{base}/subscriptions/{name}-sub", json={"topic": f"projects/{servers.PUBSUB_PROJECT}/topics/{name}",
                                                         "ackDeadlineSeconds": 10}).raise_for_status()
    return base


def test_pubsub_acknowledges_after_saving_and_knows_a_redelivery_by_its_id(db, world, storage, monkeypatch):
    import httpx

    name = f"orders_{uuid.uuid4().hex[:6]}"
    base = _pubsub_topic(name)
    messages = [{"data": base64.b64encode(json.dumps({"order": i}).encode()).decode(), "attributes": {"src": "shop"}}
                for i in range(6)]
    httpx.post(f"{base}/topics/{name}:publish", json={"messages": messages}).raise_for_status()
    source_id = _source(db, world, "pubsub", {"project": servers.PUBSUB_PROJECT, "subscription": f"{name}-sub",
                                              "emulator_host": servers.PUBSUB.replace("http://", "")})
    kind = KINDS["pubsub"]
    original = kind.read

    def saved_but_acknowledgement_lost(*args, **kwargs):
        batch = original(*args, **kwargs)
        batch.after_commit = batch.abandon  # the messages come straight back, as after a lost acknowledgement
        return batch

    monkeypatch.setattr(kind, "read", saved_but_acknowledgement_lost)
    streams.run_pass(db, source_id, owner="test-runner", storage_backend=storage, settings=SETTINGS)
    assert _orders(db, source_id) == list(range(6))
    monkeypatch.setattr(kind, "read", original)
    _pass(db, source_id, storage)  # the same six again, recognised by their ids, then acknowledged
    _pass(db, source_id, storage)
    assert _orders(db, source_id) == list(range(6))
    assert _count(db, source_id) == 6


# ----------------------------------------------------------------------- Pulsar


def test_pulsar_reads_from_the_saved_message_id(db, world, storage):
    import logging

    import pulsar

    topic = f"persistent://public/default/orders_{uuid.uuid4().hex[:6]}"
    client = pulsar.Client(servers.PULSAR, logger=logging.getLogger("pulsar-test"))
    producer = client.create_producer(topic)
    for i in range(8):
        producer.send(json.dumps({"order": i}).encode(), properties={"src": "shop"})
    source_id = _source(db, world, "pulsar", {"service_url": servers.PULSAR, "topic": topic})
    _pass(db, source_id, storage)
    for i in range(8, 10):
        producer.send(json.dumps({"order": i}).encode())
    _pass(db, source_id, storage)
    _pass(db, source_id, storage)
    client.close()
    assert _orders(db, source_id) == list(range(10))


# --------------------------------------------------------------------- RabbitMQ


def test_rabbitmq_recognises_a_redelivery_with_an_id_and_says_one_without_can_repeat(db, world, storage, monkeypatch):
    import pika

    queue = f"orders_{uuid.uuid4().hex[:6]}"
    connection = pika.BlockingConnection(pika.URLParameters(servers.RABBITMQ))
    channel = connection.channel()
    channel.queue_declare(queue=queue, durable=True)
    for i in range(4):
        channel.basic_publish("", queue, json.dumps({"order": i}).encode(),
                              pika.BasicProperties(message_id=f"order-{i}" if i < 2 else None))
    connection.close()
    source_id = _source(db, world, "rabbitmq", {"url": servers.RABBITMQ, "queue": queue})
    kind = KINDS["rabbitmq"]
    original = kind.read

    def saved_but_acknowledgement_lost(*args, **kwargs):
        batch = original(*args, **kwargs)
        batch.after_commit = batch.abandon
        return batch

    monkeypatch.setattr(kind, "read", saved_but_acknowledgement_lost)
    streams.run_pass(db, source_id, owner="test-runner", storage_backend=storage, settings=SETTINGS)
    monkeypatch.setattr(kind, "read", original)
    _pass(db, source_id, storage)
    _pass(db, source_id, storage)
    # Orders 0 and 1 had ids: saved once. 2 and 3 had none: saved twice, as the guarantee says.
    assert _orders(db, source_id) == [0, 1, 2, 2, 3, 3]
    assert streams.get_source(db, world["project"].id, source_id, world["user"]).guarantee == "at_least_once"


# ------------------------------------------------------------------------- NATS


def test_nats_reads_from_the_saved_stream_sequence(db, world, storage):
    import nats

    stream = f"ORDERS_{uuid.uuid4().hex[:6]}"

    async def publish(start: int, count: int, create: bool = False) -> None:
        client = await nats.connect(servers.NATS)
        js = client.jetstream()
        if create:
            await js.add_stream(name=stream, subjects=[f"{stream}.>"])
        for i in range(start, start + count):
            await js.publish(f"{stream}.created", json.dumps({"order": i}).encode())
        await client.close()

    asyncio.run(publish(0, 9, create=True))
    source_id = _source(db, world, "nats", {"servers": servers.NATS, "stream": stream})
    _pass(db, source_id, storage)
    asyncio.run(publish(9, 3))
    _pass(db, source_id, storage)
    _pass(db, source_id, storage)
    assert _orders(db, source_id) == list(range(12))
    assert streams.cursor_of(db.get(StreamSource, source_id))["seq"] == 12


# ------------------------------------------------------------------------- MQTT


def test_mqtt_collects_what_arrived_while_away_through_its_session(db, world, storage):
    import paho.mqtt.publish as publish

    topic = f"orders/{uuid.uuid4().hex[:6]}"
    source_id = _source(db, world, "mqtt", {"host": servers.MQTT[0], "port": servers.MQTT[1], "topic": f"{topic}/#"})
    _pass(db, source_id, storage)  # makes the session and subscribes
    for i in range(30):  # more than Mosquitto sends before an acknowledgement (20)
        publish.single(f"{topic}/created", json.dumps({"order": i}), qos=1, hostname=servers.MQTT[0], port=servers.MQTT[1])
    _pass(db, source_id, storage)
    assert _orders(db, source_id) == list(range(30))
    _pass(db, source_id, storage)
    assert _count(db, source_id) == 30  # acknowledged: not sent again


# --------------------------------------------------------- a live recipe on a queue


def test_a_live_recipe_summarises_kafka_messages_by_window(db, world, storage):
    from confluent_kafka import Producer

    from confluent_kafka.admin import AdminClient, NewTopic

    topic = f"sales_{uuid.uuid4().hex[:6]}"
    admin = AdminClient({"bootstrap.servers": servers.KAFKA})  # kept: the future needs its client
    admin.create_topics([NewTopic(topic, num_partitions=1)])[topic].result()
    producer = Producer({"bootstrap.servers": servers.KAFKA})
    source_id = _source(db, world, "kafka", {"bootstrap_servers": servers.KAFKA, "topic": topic})
    recipe = live_recipes.create_recipe(db, world["project"].id, source_id, LiveRecipeCreate(
        name="sales per minute", window={"kind": "tumbling", "size_seconds": 60, "time_column": "at"},
        group_by=["region"], measures=[{"name": "revenue", "op": "sum", "column": "amount"}]), world["user"])
    for at, region, amount in [("10:00:10", "north", 5), ("10:00:20", "north", 7), ("10:01:05", "south", 3)]:
        producer.produce(topic, value=json.dumps({"at": f"2026-10-15T{at}Z", "region": region, "amount": amount}))
    producer.flush()
    _pass(db, source_id, storage)
    results = live_recipes.recipe_results(db, world["project"].id, source_id, recipe.id, world["user"]).items
    assert sorted((r.window_start.strftime("%H:%M"), r.group[0], r.values["revenue"]) for r in results) == [
        ("10:00", "north", 12.0), ("10:01", "south", 3.0)]
