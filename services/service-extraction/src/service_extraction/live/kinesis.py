"""Amazon Kinesis Data Streams (D1, roadmap Phase 20).

Every shard is read from the sequence number after the last one saved,
which is kept with the events, so a restart carries on exactly there and
each record is saved once. A shard closed by resharding is read to its end;
its children are listed and read too. Starting "from now" saves the moment
of the first read and reads each shard from that time, so nothing that
arrives between reads is skipped.

Tested against a Kinesis test server (etspaceman/kinesis-mock) that answers
the way AWS documents the API; `Endpoint` points elsewhere for that or for a
VPC endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from service_extraction.live.base import (
    Batch, LiveError, LiveField, LiveKind, Message, Outcome, host_of, position_of, queue_payload,
)


class KinesisKind(LiveKind):
    key = "kinesis"
    label = "Amazon Kinesis"
    description = "Read a Kinesis data stream, every shard, from where Pipewright last stopped."
    fields = (
        LiveField("region", "Region", placeholder="eu-west-2"),
        LiveField("stream", "Stream"),
        LiveField("access_key_id", "Access key id"),
        LiveField("secret_access_key", "Secret access key", kind="secret"),
        LiveField("session_token", "Session token", kind="secret", required=False),
        LiveField("start_from", "Start from", kind="select", required=False, default="earliest",
                  options=("earliest", "latest"),
                  help="The first time only: every record kept, or only those that arrive from now."),
        LiveField("endpoint_url", "Endpoint", required=False,
                  help="Leave blank for AWS. Set it for a VPC endpoint or a test server."),
    )
    guarantee = "position"
    guarantee_note = "Each shard's sequence number is saved with the events."
    verified_by = "test_live_queues.py"
    driver_module = "boto3"
    driver_package = "boto3"

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        return [h for h in (host_of(settings.get("endpoint_url")),) if h]

    def _client(self, settings: dict[str, Any]):
        import boto3
        from botocore.config import Config

        return boto3.client(
            "kinesis", region_name=settings["region"], endpoint_url=settings.get("endpoint_url") or None,
            aws_access_key_id=settings["access_key_id"], aws_secret_access_key=settings["secret_access_key"],
            aws_session_token=settings.get("session_token") or None,
            config=Config(connect_timeout=10, read_timeout=20, retries={"max_attempts": 2}),
        )

    def _shards(self, client, stream: str) -> list[dict[str, Any]]:
        shards: list[dict[str, Any]] = []
        token = None
        while True:
            page = client.list_shards(NextToken=token) if token else client.list_shards(StreamName=stream)
            shards.extend(page.get("Shards", []))
            token = page.get("NextToken")
            if not token:
                return shards

    def test(self, settings: dict[str, Any]) -> Outcome:
        try:
            client = self._client(settings)
            summary = client.describe_stream_summary(StreamName=settings["stream"])["StreamDescriptionSummary"]
        except Exception as exc:  # noqa: BLE001 - AWS's own words are the answer
            return Outcome(False, f"Could not read the stream: {str(exc)[:300]}")
        status = summary.get("StreamStatus")
        if status not in ("ACTIVE", "UPDATING"):
            return Outcome(False, f"The stream is {str(status).lower()}, not active.")
        return Outcome(True, f"Connected. {settings['stream']} has {summary.get('OpenShardCount', 0)} open shards "
                             f"and keeps records for {summary.get('RetentionPeriodHours', 24)} hours.")

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        cursor = dict(cursor or {})
        positions: dict[str, str] = dict(cursor.get("shards") or {})
        since = cursor.get("since")
        if not positions and since is None and (settings.get("start_from") or "earliest") == "latest":
            since = datetime.now(UTC).isoformat()
        client = self._client(settings)
        try:
            shards = self._shards(client, settings["stream"])
        except Exception as exc:  # noqa: BLE001
            raise LiveError(f"Could not list the stream's shards: {str(exc)[:300]}") from exc
        messages: list[Message] = []
        more = False
        for shard in sorted(shards, key=lambda s: s["ShardId"]):
            if len(messages) >= limit:
                more = True
                break
            shard_id = shard["ShardId"]
            if positions.get(shard_id) == "closed":
                continue
            if shard_id in positions:
                request = {"ShardIteratorType": "AFTER_SEQUENCE_NUMBER", "StartingSequenceNumber": positions[shard_id]}
            elif since is not None:
                request = {"ShardIteratorType": "AT_TIMESTAMP", "Timestamp": datetime.fromisoformat(since)}
            else:
                request = {"ShardIteratorType": "TRIM_HORIZON"}
            try:
                iterator = client.get_shard_iterator(StreamName=settings["stream"], ShardId=shard_id, **request)["ShardIterator"]
            except client.exceptions.InvalidArgumentException as exc:
                raise LiveError(f"Shard {shard_id} no longer has the records after the saved position ({exc}). "
                                "Start the feed again.") from exc
            page_size = min(10_000, limit)
            for _ in range(20):  # empty pages are normal near the end of a shard
                if iterator is None or len(messages) >= limit:
                    break
                # One page size throughout: records past the limit are left for the next read,
                # which starts after the last one kept.
                page = client.get_records(ShardIterator=iterator, Limit=page_size)
                for record in page.get("Records", []):
                    sequence = record["SequenceNumber"]
                    last = positions.get(shard_id)
                    if last not in (None, "closed") and int(sequence) <= int(last):
                        continue  # already saved; a shard never goes backwards
                    if len(messages) >= limit:
                        more = True
                        break
                    messages.append(Message(
                        "message",
                        queue_payload(value=record.get("Data"), key=record.get("PartitionKey"),
                                      published_at=record.get("ApproximateArrivalTimestamp"),
                                      shard=shard_id, sequence=sequence),
                        position=position_of(f"{shard_id}:{sequence}"),
                    ))
                    positions[shard_id] = sequence
                if more:
                    break
                iterator = page.get("NextShardIterator")
                lag = int(page.get("MillisBehindLatest") or 0)
                if iterator is None:
                    positions[shard_id] = "closed"  # resharded: read to its end
                    break
                if not page.get("Records") and lag == 0:
                    break
            if iterator is not None and len(messages) >= limit:
                more = True
        saved: dict[str, Any] = {"shards": positions}
        if since is not None and not all(shard["ShardId"] in positions for shard in shards):
            saved["since"] = since
        return Batch(messages=messages, cursor=saved, more=more)
