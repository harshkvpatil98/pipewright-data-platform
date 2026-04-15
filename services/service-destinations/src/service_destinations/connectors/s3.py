from __future__ import annotations

import time
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def check_s3_connection(config: dict[str, Any]) -> tuple[bool, str, float | None, list[str]]:
    warnings: list[str] = []
    region = config.get("region") or "us-east-1"
    start = time.perf_counter()
    try:
        session = boto3.session.Session(
            aws_access_key_id=config["access_key_id"],
            aws_secret_access_key=config["secret_access_key"],
            region_name=region,
        )
        client = session.client(
            "s3",
            config=boto3.session.Config(connect_timeout=8, read_timeout=12, retries={"max_attempts": 2}),
        )
        client.head_bucket(Bucket=config["bucket"])
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Error")
        return False, f"S3 check failed ({code}).", None, warnings
    except BotoCoreError as exc:
        msg = str(exc).splitlines()[0][:400]
        return False, f"S3 error: {msg}", None, warnings
    except Exception:  # noqa: BLE001
        return False, "S3 connection check failed.", None, warnings

    latency_ms = (time.perf_counter() - start) * 1000.0
    return True, "Bucket is reachable (head_bucket succeeded).", latency_ms, warnings
