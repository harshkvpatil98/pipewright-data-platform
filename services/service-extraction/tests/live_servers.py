"""Where the live-source test servers are (D1).

One table for the round-trip tests and for `scripts/check-live-servers.py`.
The addresses are the ports `docker-compose.live.yml` publishes, which the
`live` CI job starts too. With `LIVE_TEST_SERVERS=1` unset, every round trip
skips and says so; CI sets it, and its check script fails the job if a server
is missing, so a skip there can never pass for a test.
"""

from __future__ import annotations

import os

ENABLED = os.environ.get("LIVE_TEST_SERVERS") == "1"
REASON = "live test servers are off; start docker-compose.live.yml and set LIVE_TEST_SERVERS=1"

POSTGRES = {"host": "127.0.0.1", "port": 15433, "database": "platform", "username": "platform", "password": "platform"}
POSTGRES_URL = "postgresql+psycopg://platform:platform@127.0.0.1:15433/platform"
MYSQL = {"host": "127.0.0.1", "port": 13316, "database": "platform", "username": "root", "password": "platform"}
MYSQL_URL = "mysql+pymysql://root:platform@127.0.0.1:13316/platform"
MONGO_URI = "mongodb://127.0.0.1:27018/?replicaSet=rs0&directConnection=true"
SQLSERVER = {"host": "127.0.0.1", "port": 14333, "username": "sa", "password": "Platform-pass-1"}
KAFKA = "127.0.0.1:19092"
EVENT_HUBS = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)
EVENT_HUB_NAME = "orders"
KINESIS = "http://127.0.0.1:14568"
PUBSUB = "http://127.0.0.1:18085"
PUBSUB_PROJECT = "pipewright-test"
PULSAR = "pulsar://127.0.0.1:16650"
PULSAR_ADMIN = "http://127.0.0.1:18081"
RABBITMQ = "amqp://platform:platform@127.0.0.1:15674/"
NATS = "nats://127.0.0.1:14222"
MQTT = ("127.0.0.1", 11883)
