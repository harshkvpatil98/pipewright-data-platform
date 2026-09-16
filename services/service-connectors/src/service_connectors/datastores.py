"""Data stores this platform knows about but cannot yet drive.

The roadmap's catalogue names a set of engines -- Cassandra, Redis, HBase,
Timestream, HDFS and friends -- that are neither SQL databases the dialect table
can reach nor HTTP APIs a manifest can describe. Each needs its own client
library and its own idea of what a "row" is.

They are in the catalogue anyway, declared, with three things attached: the
package that would have to be installed, why they do not work here, and **what
to do instead**. That last part is the reason this file exists rather than an
empty gap in the picker: a lot of these publish a second interface that the
platform *can* drive today -- Cassandra and ScyllaDB through Stargate's REST
gateway, ScyllaDB through its DynamoDB-compatible API, HDFS through WebHDFS --
and somebody looking for Cassandra should be told that rather than concluding
the platform cannot reach their data.

The posture is the Phase 04 rule applied honestly: capabilities describe what
works *here*. Every entry declares only `test`, `available` is False, and
`test()` answers with the reason. Nothing here claims to read anything.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field

from service_connectors.protocol import ConfigField, ConnectorSpec, Tier


@dataclass(frozen=True)
class DataStore:
    """One engine, described well enough to be useful while unimplemented."""

    key: str
    label: str
    category: str
    description: str
    #: The client library a working connector would need.
    package: str
    #: The interface this platform *can* reach today, when there is one.
    instead: str
    docs_url: str | None = None
    config_fields: tuple[ConfigField, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.instead:
            raise ValueError(
                f"{self.key} has no alternative to offer. A catalogue entry that "
                "cannot do anything and cannot say what would is noise."
            )

    def unavailable_reason(self) -> str:
        installed = importlib.util.find_spec(_root(self.package)) is not None
        head = (
            f"The '{self.package}' package is installed, but this platform has no "
            f"{self.label} client wired up yet."
            if installed
            else f"{self.label} needs the '{self.package}' package, which is not "
            "installed on this deployment, and a client this platform does not have yet."
        )
        return f"{head} {self.instead}"


def _root(package: str) -> str:
    return package.replace("-", "_").split("[")[0]


def spec_for(store: DataStore) -> ConnectorSpec:
    return ConnectorSpec(
        type=store.key,
        label=store.label,
        category=store.category,
        description=store.description,
        config_fields=store.config_fields,
        # Only `test`, because only `test` works: it reports why. Declaring
        # `read` would make `supports("read")` a promise nothing keeps.
        capabilities=frozenset({"test"}),
        driver_package=store.package,
        documentation_url=store.docs_url,
        available=False,
        unavailable_reason=store.unavailable_reason(),
        tier=Tier.SPEC_ONLY,
        origin="declared",
    )


_SERVER = (
    ConfigField("host", "Host", placeholder="node-1.internal"),
    ConfigField("port", "Port", kind="number", required=False),
    ConfigField("username", "Username", required=False),
    ConfigField("password", "Password", kind="secret", required=False),
)

TABLE: dict[str, DataStore] = {}


def _s(store: DataStore) -> DataStore:
    if store.key in TABLE:
        raise ValueError(f"'{store.key}' is already a data store.")
    TABLE[store.key] = store
    return store


# ----------------------------------------------------- wide-column and key-value

_s(DataStore(
    key="cassandra", label="Apache Cassandra", category="nosql",
    description="Read tables from a Cassandra keyspace.",
    package="cassandra-driver",
    instead=(
        "A Cassandra cluster running the Stargate gateway publishes a REST API that "
        "the REST connector reads today."
    ),
    docs_url="https://docs.datastax.com/en/developer/python-driver/",
    config_fields=(*_SERVER, ConfigField("keyspace", "Keyspace")),
))
_s(DataStore(
    key="scylladb", label="ScyllaDB", category="nosql",
    description="Read tables from ScyllaDB.",
    package="scylla-driver",
    instead=(
        "ScyllaDB's Alternator interface is DynamoDB-compatible, and the DynamoDB "
        "connector reads it today."
    ),
    docs_url="https://python-driver.docs.scylladb.com/",
    config_fields=(*_SERVER, ConfigField("keyspace", "Keyspace")),
))
_s(DataStore(
    key="hbase", label="Apache HBase", category="nosql",
    description="Read tables from HBase.",
    package="happybase",
    # Phoenix would be the other answer here, but it has no entry in the
    # dialect table, and pointing somebody at a connector that does not exist
    # is worse than the gap it was meant to fill.
    instead="HBase's Stargate REST gateway is readable through the REST connector.",
    docs_url="https://happybase.readthedocs.io/",
    config_fields=(*_SERVER, ConfigField("table", "Table", required=False)),
))
_s(DataStore(
    key="aerospike", label="Aerospike", category="nosql",
    description="Read records from an Aerospike namespace.",
    package="aerospike",
    instead="Aerospike's REST gateway is readable through the REST connector.",
    docs_url="https://aerospike-python-client.readthedocs.io/",
    config_fields=(*_SERVER, ConfigField("namespace", "Namespace")),
))
_s(DataStore(
    key="redis", label="Redis", category="nosql",
    description="Read keys and hashes from Redis.",
    package="redis",
    instead=(
        "Redis is a cache rather than a source of record; the system writing to it "
        "usually has a database this platform can read directly."
    ),
    docs_url="https://redis.readthedocs.io/",
    config_fields=(
        *_SERVER,
        ConfigField("db", "Database number", kind="number", required=False, default=0),
        ConfigField("pattern", "Key pattern", required=False, default="*"),
    ),
))
_s(DataStore(
    key="couchbase", label="Couchbase", category="nosql",
    description="Read documents from a Couchbase bucket.",
    package="couchbase",
    instead=(
        "Couchbase's Query Service answers N1QL over HTTP, which the REST connector "
        "reads today."
    ),
    docs_url="https://docs.couchbase.com/python-sdk/current/hello-world/start-using-sdk.html",
    config_fields=(*_SERVER, ConfigField("bucket", "Bucket")),
))
_s(DataStore(
    key="arangodb", label="ArangoDB", category="nosql",
    description="Read documents from an ArangoDB collection.",
    package="python-arango",
    instead="ArangoDB's HTTP API answers AQL, which the REST connector reads today.",
    docs_url="https://docs.python-arango.com/",
    config_fields=(*_SERVER, ConfigField("database", "Database")),
))

# ------------------------------------------------------------------ time series

_s(DataStore(
    key="timestream", label="Amazon Timestream", category="timeseries",
    description="Read time series from Amazon Timestream.",
    package="boto3",
    instead=(
        "Timestream answers SQL through its query API; exporting to S3 makes it "
        "readable through the S3 connector today."
    ),
    docs_url="https://docs.aws.amazon.com/timestream/",
    config_fields=(
        ConfigField("region", "Region", default="us-east-1"),
        ConfigField("database", "Database"),
        ConfigField("access_key_id", "Access key id"),
        ConfigField("secret_access_key", "Secret access key", kind="secret"),
    ),
))

# --------------------------------------------------------------------- lakehouse

_s(DataStore(
    key="hdfs", label="HDFS", category="lakehouse",
    description="Read files from a Hadoop distributed filesystem.",
    package="hdfs",
    instead=(
        "WebHDFS is an HTTP API the REST connector reads, and a cluster with Hive "
        "or Trino in front of it is readable through the dialect table."
    ),
    docs_url="https://hdfscli.readthedocs.io/",
    config_fields=(
        ConfigField("namenode_url", "NameNode URL", placeholder="http://namenode:9870"),
        ConfigField("path", "Path", default="/"),
        ConfigField("username", "Username", required=False),
    ),
))


def all_datastores() -> list[DataStore]:
    return [TABLE[key] for key in sorted(TABLE)]
