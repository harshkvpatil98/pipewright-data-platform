#!/usr/bin/env python
"""Fail if a server a live-source kind is tested against is not working.

The round-trip tests skip a server they cannot reach, which is right on a
laptop and wrong in CI: a skipped test is a green build, and the live-source
tier badges rest on that build. So the `live` CI job checks first that every
server in `docker-compose.live.yml` answers the way its test needs (logical
decoding on, a row-based binary log, a replica set, SQL Server Agent running,
a broker that lists its topics) and says which one does not.

    .venv/bin/python scripts/check-live-servers.py [--wait SECONDS]
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "service-extraction" / "tests"))

import live_servers as servers  # noqa: E402


def _postgres() -> None:
    import sqlalchemy as sa

    engine = sa.create_engine(servers.POSTGRES_URL)
    try:
        with engine.connect() as conn:
            level = conn.execute(sa.text("SHOW wal_level")).scalar()
        if level != "logical":
            raise RuntimeError(f"wal_level is {level}, not logical")
    finally:
        engine.dispose()


def _mysql() -> None:
    import sqlalchemy as sa

    engine = sa.create_engine(servers.MYSQL_URL)
    try:
        with engine.connect() as conn:
            fmt = conn.execute(sa.text("SELECT @@binlog_format")).scalar()
        if fmt != "ROW":
            raise RuntimeError(f"binlog_format is {fmt}, not ROW")
    finally:
        engine.dispose()


def _mongo() -> None:
    import pymongo

    client = pymongo.MongoClient(servers.MONGO_URI, serverSelectionTimeoutMS=3000)
    try:
        status = client.admin.command("replSetGetStatus")
        if not status.get("ok"):
            raise RuntimeError("the replica set is not initiated")
    finally:
        client.close()


def _sqlserver() -> None:
    import pymssql

    conn = pymssql.connect(server=servers.SQLSERVER["host"], port=servers.SQLSERVER["port"],
                           user=servers.SQLSERVER["username"], password=servers.SQLSERVER["password"],
                           login_timeout=5)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status_desc FROM sys.dm_server_services WHERE servicename LIKE 'SQL Server Agent%'")
        row = cursor.fetchone()
        if not row or row[0] != "Running":
            raise RuntimeError("SQL Server Agent is not running, and change capture needs it")
    finally:
        conn.close()


def _kafka(bootstrap: str, **extra: str) -> None:
    from confluent_kafka.admin import AdminClient

    client = AdminClient({"bootstrap.servers": bootstrap, "socket.timeout.ms": 5000, **extra})
    client.list_topics(timeout=5)


def _event_hubs() -> None:
    _kafka("localhost:9092", **{"security.protocol": "SASL_PLAINTEXT", "sasl.mechanisms": "PLAIN",
                                "sasl.username": "$ConnectionString", "sasl.password": servers.EVENT_HUBS})


def _kinesis() -> None:
    import boto3

    client = boto3.client("kinesis", endpoint_url=servers.KINESIS, region_name="us-east-1",
                          aws_access_key_id="test", aws_secret_access_key="test")
    client.list_streams()


def _http(url: str) -> None:
    import httpx

    response = httpx.get(url, timeout=5)
    response.raise_for_status()


def _rabbitmq() -> None:
    import pika

    connection = pika.BlockingConnection(pika.URLParameters(servers.RABBITMQ))
    connection.close()


def _nats() -> None:
    import asyncio

    import nats

    async def probe() -> None:
        client = await nats.connect(servers.NATS, connect_timeout=3, max_reconnect_attempts=0)
        try:
            await client.jetstream().account_info()
        finally:
            await client.close()

    asyncio.run(probe())


def _mqtt() -> None:
    with socket.create_connection(servers.MQTT, timeout=3):
        pass


CHECKS = {
    "PostgreSQL (logical decoding)": _postgres,
    "MySQL (row-based binary log)": _mysql,
    "MongoDB (replica set)": _mongo,
    "SQL Server (with its Agent)": _sqlserver,
    "Kafka": lambda: _kafka(servers.KAFKA),
    "Event Hubs emulator (Kafka endpoint)": _event_hubs,
    "Kinesis test server": _kinesis,
    "Pub/Sub emulator": lambda: _http(f"{servers.PUBSUB}/v1/projects/{servers.PUBSUB_PROJECT}/topics"),
    "Pulsar": lambda: _http(f"{servers.PULSAR_ADMIN}/admin/v2/clusters"),
    "RabbitMQ": _rabbitmq,
    "NATS JetStream": _nats,
    "MQTT (Mosquitto)": _mqtt,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wait", type=float, default=0, help="Keep retrying for this many seconds.")
    args = parser.parse_args()
    deadline = time.monotonic() + args.wait
    pending = dict(CHECKS)
    problems: dict[str, str] = {}
    while True:
        for name, check in list(pending.items()):
            try:
                check()
            except Exception as exc:  # noqa: BLE001 - any failure is the answer
                problems[name] = f"{exc.__class__.__name__}: {str(exc)[:160]}"
            else:
                problems.pop(name, None)
                pending.pop(name)
                print(f"ok  {name}")
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(3)
    if problems:
        print("\nLive-source test servers not working:", file=sys.stderr)
        for name, problem in problems.items():
            print(f"  - {name}: {problem}", file=sys.stderr)
        print("\nEach live-source kind claims tier 2 because its round trip runs against one of "
              "these on every change. Start them (docker-compose.live.yml) or lower the claim.", file=sys.stderr)
        return 1
    print("All live-source test servers are working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
