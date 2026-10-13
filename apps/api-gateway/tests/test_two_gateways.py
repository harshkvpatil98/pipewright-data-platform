"""Two gateways, one bucket, one database (adoption-readiness A7, X2).

The claim is that a gateway keeps nothing of its own: files are in the bucket,
upload sessions and everything else in the database. This starts two real
gateway processes on both, sends a large file in chunks to *both* of them,
finishes the upload on the second, and reads the dataset back on the first.
Encryption at rest is on, so the bucket is also checked to hold only
encrypted bytes.

It needs an S3-compatible store: STORAGE_TEST_S3_ENDPOINT, _BUCKET, _KEY and
_SECRET (CI runs MinIO; `docker-compose.connectors.yml` has one on 19000).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.encrypted import is_encrypted
from shared_python.storage.s3 import S3StorageBackend

STORE = {name: os.environ.get(f"STORAGE_TEST_S3_{name}") for name in ("ENDPOINT", "BUCKET", "KEY", "SECRET")}
pytestmark = pytest.mark.skipif(
    not all(STORE.values()),
    reason="Set STORAGE_TEST_S3_ENDPOINT, _BUCKET, _KEY and _SECRET to run two gateways against one bucket.",
)

GATEWAY_SRC = Path(__file__).resolve().parents[1]
PASSWORD = "two-gateways-password"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_until_up(base: str, process: subprocess.Popen) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"A gateway exited: {process.stdout.read().decode(errors='replace')[-2000:]}")
        try:
            with urllib.request.urlopen(f"{base}/api/v1/health/live", timeout=2):
                return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError("A gateway did not start within 60 seconds.")


@pytest.fixture()
def gateways(tmp_path):
    database = f"sqlite:///{tmp_path / 'shared.db'}"
    engine = create_engine(database)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            User.__table__.insert().values(
                id=uuid.uuid4(), username="operator", password_hash=hash_password(PASSWORD), role="admin",
                is_active=True,
            )
        )
    engine.dispose()

    prefix = f"two-gateways/{uuid.uuid4().hex}"
    env = {
        **os.environ,
        "DATABASE_URL": database,
        "STORAGE_BACKEND": "s3",
        "STORAGE_S3_BUCKET": STORE["BUCKET"],
        "STORAGE_S3_PREFIX": prefix,
        "STORAGE_S3_ENDPOINT_URL": STORE["ENDPOINT"],
        "STORAGE_S3_REGION": "us-east-1",
        "STORAGE_S3_ACCESS_KEY_ID": STORE["KEY"],
        "STORAGE_S3_SECRET_ACCESS_KEY": STORE["SECRET"],
        "STORAGE_ENCRYPTION_KEY": base64.b64encode(os.urandom(32)).decode(),
        "AUTH_JWT_SECRET": "two-gateways-shared-signing-secret-0123456789",
        "BACKEND_CORS_ORIGINS": json.dumps(["http://localhost:3000"]),
        "MAX_UPLOAD_SIZE_BYTES": str(64 * 1024 * 1024),
        "DB_POOL_SIZE": "2",
    }
    bucket = S3StorageBackend(
        bucket=STORE["BUCKET"], prefix=prefix, endpoint_url=STORE["ENDPOINT"], region="us-east-1",
        access_key_id=STORE["KEY"], secret_access_key=STORE["SECRET"],
    )
    try:
        bucket.client.head_bucket(Bucket=bucket.bucket)
    except Exception:  # noqa: BLE001 - created when missing
        bucket.client.create_bucket(Bucket=bucket.bucket)

    processes, bases = [], []
    for _ in range(2):
        port = _free_port()
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api_gateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=GATEWAY_SRC, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        processes.append(process)
        bases.append(f"http://127.0.0.1:{port}")
    try:
        for base, process in zip(bases, processes):
            _wait_until_up(base, process)
        yield bases, bucket
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=10)


def test_a_chunked_upload_spans_two_gateways_and_reads_back_on_either(gateways) -> None:
    (first, second), bucket = gateways
    token = httpx.post(f"{first}/api/v1/auth/login", json={"username": "operator", "password": PASSWORD}).json()[
        "access_token"
    ]
    auth = {"Authorization": f"Bearer {token}"}
    project = httpx.post(f"{second}/api/v1/projects", json={"name": "Shared"}, headers=auth).json()["id"]

    # A little over two chunks of 8MB, so the chunks can go to both gateways.
    rows = [f"{index},customer {index},{index % 97}.5" for index in range(560_000)]
    body = ("order_id,customer,amount\n" + "\n".join(rows) + "\n").encode()
    started = httpx.post(
        f"{first}/api/v1/projects/{project}/datasets/uploads",
        json={"file_name": "orders.csv", "total_bytes": len(body), "content_type": "text/csv"},
        headers=auth,
    ).json()
    size = started["chunk_bytes"]
    chunks = [body[start : start + size] for start in range(0, len(body), size)]
    assert len(chunks) >= 2
    for index, chunk in enumerate(chunks):
        gateway = (first, second)[index % 2]
        answer = httpx.put(
            f"{gateway}/api/v1/projects/{project}/datasets/uploads/{started['upload_id']}/chunks/{index}",
            files={"chunk": ("chunk", chunk, "application/octet-stream")}, headers=auth, timeout=60,
        )
        assert answer.status_code == 200, answer.text

    finished = httpx.post(
        f"{second}/api/v1/projects/{project}/datasets/uploads/{started['upload_id']}/complete",
        json={"dataset_name": "Orders"}, headers=auth, timeout=120,
    )
    assert finished.status_code == 201, finished.text
    dataset = finished.json()["dataset"]["id"]

    preview = httpx.get(f"{first}/api/v1/projects/{project}/datasets/{dataset}/preview", headers=auth).json()
    assert preview["rows"][0]["customer"] == "customer 0"
    download = httpx.get(
        f"{first}/api/v1/projects/{project}/datasets/{dataset}/download?format=csv", headers=auth, timeout=120
    )
    assert download.status_code == 200
    assert len(download.text.strip().splitlines()) == len(rows) + 1

    stored = list(bucket.list_paths())
    assert stored, "nothing reached the bucket"
    assert all(is_encrypted(bucket.read_bytes(path)) for path in stored)
