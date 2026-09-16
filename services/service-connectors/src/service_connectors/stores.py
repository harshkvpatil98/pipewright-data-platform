"""Object stores as a table, crossed with the format registry.

The third generator, and the cheapest of the three. Most of the object storage
world speaks the S3 API, so those stores are the tested S3 connector with an
endpoint template filled in -- genuinely working code, not a declaration. The
rest need their own SDK, and are declared with the package to install, the same
way an unavailable database is.

The "matrix" in the roadmap is not a metaphor: a store reads any format the
registry knows, so adding a format adds it to every store at once. That product
is what `combinations()` reports, and it is why the format registry was worth
extending before this file rather than after.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from service_connectors.formats import FORMATS
from service_connectors.protocol import ConfigField, ConnectorSpec, Tier

#: S3-compatible stores need one thing filled in and nothing else.
S3_COMPATIBLE = "s3_compatible"
#: Everything else brings its own SDK.
NATIVE = "native"


@dataclass(frozen=True)
class Store:
    key: str
    label: str
    kind: str
    description: str
    #: For S3-compatible stores: the endpoint, with `{}` for a user setting.
    endpoint_template: str | None = None
    #: The setting that fills the template, when there is one.
    endpoint_field: ConfigField | None = None
    #: For native stores, the package that supplies the SDK. Empty when the
    #: standard library already has it -- FTP is `ftplib`, and claiming it
    #: needs an install would send somebody to pip for nothing.
    package: str | None = None
    builtin: bool = False
    #: True when this platform has a client wired up, not merely a library
    #: available. An installed SDK is not an implemented connector, and a spec
    #: that promised `read` because `ftplib` exists would be promising
    #: something no code here delivers.
    implemented: bool = False
    extra_fields: tuple[ConfigField, ...] = ()
    docs_url: str | None = None
    tier: Tier = Tier.SPEC_ONLY
    verified_by: str | None = None

    def __post_init__(self) -> None:
        if self.kind == S3_COMPATIBLE and self.endpoint_template is None:
            raise ValueError(f"{self.key} is S3-compatible but has no endpoint.")
        if self.kind == NATIVE and not self.package and not self.builtin:
            raise ValueError(
                f"{self.key} is native but names no package. Set builtin=True if the "
                "standard library supplies it."
            )
        if self.tier is not Tier.SPEC_ONLY and not self.verified_by:
            raise ValueError(f"{self.key} claims tier {int(self.tier)} without saying why.")

    def available(self) -> tuple[bool, str | None]:
        if self.kind == NATIVE and not self.implemented:
            return False, (
                f"{self.label} is in the catalogue but this platform has no client for "
                "it yet. Use an S3-compatible endpoint if the store offers one."
            )
        if self.builtin:
            return True, None
        package = "boto3" if self.kind == S3_COMPATIBLE else (self.package or "")
        root = package.replace("-", "_").split("[")[0]
        if importlib.util.find_spec(root) is not None:
            return True, None
        return False, (
            f"{self.label} needs the '{package}' package, which is not installed on "
            "this deployment."
        )


TABLE: dict[str, Store] = {}


def _s(store: Store) -> Store:
    if store.key in TABLE:
        raise ValueError(f"'{store.key}' is already a store.")
    TABLE[store.key] = store
    return store


# ------------------------------------------------------------ S3-compatible
#
# Each of these publishes an S3-compatible endpoint, so each is the S3
# connector with its address filled in. That is not a shortcut; it is the
# reason S3's API became the interface everyone implements.

_s(Store(
    key="minio", label="MinIO", kind=S3_COMPATIBLE,
    description="Read objects from a self-hosted MinIO server.",
    endpoint_template="{endpoint_url}",
    endpoint_field=ConfigField("endpoint_url", "Endpoint URL", placeholder="http://minio:9000"),
    docs_url="https://min.io/docs/minio/linux/developers/python/API.html",
    tier=Tier.CONTAINER,
    verified_by="test_generators.py",
))
_s(Store(
    key="cloudflare_r2", label="Cloudflare R2", kind=S3_COMPATIBLE,
    description="Read objects from Cloudflare R2.",
    endpoint_template="https://{account_id}.r2.cloudflarestorage.com",
    endpoint_field=ConfigField("account_id", "Cloudflare account id"),
    docs_url="https://developers.cloudflare.com/r2/api/s3/api/",
    tier=Tier.CONTAINER,
    verified_by="test_generators.py",
))
_s(Store(
    key="backblaze_b2", label="Backblaze B2", kind=S3_COMPATIBLE,
    description="Read objects from Backblaze B2, through its S3-compatible API.",
    endpoint_template="https://s3.{region}.backblazeb2.com",
    endpoint_field=ConfigField("region", "Region", default="us-west-004"),
    tier=Tier.CONTAINER,
    verified_by="test_generators.py",
))
_s(Store(
    key="digitalocean_spaces", label="DigitalOcean Spaces", kind=S3_COMPATIBLE,
    description="Read objects from DigitalOcean Spaces.",
    endpoint_template="https://{region}.digitaloceanspaces.com",
    endpoint_field=ConfigField("region", "Region", default="nyc3"),
    tier=Tier.CONTAINER,
    verified_by="test_generators.py",
))
_s(Store(
    key="wasabi", label="Wasabi", kind=S3_COMPATIBLE,
    description="Read objects from Wasabi hot storage.",
    endpoint_template="https://s3.{region}.wasabisys.com",
    endpoint_field=ConfigField("region", "Region", default="us-east-1"),
    tier=Tier.CONTAINER,
    verified_by="test_generators.py",
))
_s(Store(
    key="oracle_object_storage", label="Oracle Object Storage", kind=S3_COMPATIBLE,
    description="Read objects from Oracle Cloud Object Storage, through its S3 API.",
    endpoint_template="https://{namespace}.compat.objectstorage.{region}.oraclecloud.com",
    endpoint_field=ConfigField("namespace", "Object storage namespace"),
    extra_fields=(ConfigField("region", "Region", default="us-ashburn-1"),),
    tier=Tier.CONTAINER,
    verified_by="test_generators.py",
))

# ------------------------------------------------------------------- native

_s(Store(
    key="gcs", label="Google Cloud Storage", kind=NATIVE, package="google-cloud-storage",
    description="Read objects from a GCS bucket.",
    extra_fields=(
        ConfigField("bucket", "Bucket"),
        ConfigField("prefix", "Prefix", required=False),
        ConfigField("credentials_json", "Service account JSON", kind="secret"),
    ),
    docs_url="https://cloud.google.com/storage/docs",
))
_s(Store(
    key="azure_blob", label="Azure Blob Storage", kind=NATIVE, package="azure-storage-blob",
    description="Read blobs from an Azure storage container.",
    extra_fields=(
        ConfigField("account_name", "Storage account"),
        ConfigField("container", "Container"),
        ConfigField("prefix", "Prefix", required=False),
        ConfigField("account_key", "Account key", kind="secret"),
    ),
))
_s(Store(
    key="adls_gen2", label="Azure Data Lake Storage Gen2", kind=NATIVE,
    package="azure-storage-file-datalake",
    description="Read files from an ADLS Gen2 filesystem.",
    extra_fields=(
        ConfigField("account_name", "Storage account"),
        ConfigField("filesystem", "Filesystem"),
        ConfigField("prefix", "Path", required=False),
        ConfigField("account_key", "Account key", kind="secret"),
    ),
))
_s(Store(
    key="sftp", label="SFTP", kind=NATIVE, package="paramiko",
    description="Read files from a server over SFTP.",
    extra_fields=(
        ConfigField("host", "Host"),
        ConfigField("port", "Port", kind="number", required=False, default=22),
        ConfigField("username", "Username"),
        ConfigField("password", "Password", kind="secret", required=False),
        ConfigField("private_key", "Private key", kind="secret", required=False,
                    help="Either a password or a key. The key is stored encrypted."),
        ConfigField("directory", "Directory", default="/"),
    ),
))
_s(Store(
    key="ftp", label="FTP / FTPS", kind=NATIVE, builtin=True,
    description="Read files from an FTP or FTPS server.",
    extra_fields=(
        ConfigField("host", "Host"),
        ConfigField("port", "Port", kind="number", required=False, default=21),
        ConfigField("username", "Username", required=False, default="anonymous"),
        ConfigField("password", "Password", kind="secret", required=False),
        ConfigField("directory", "Directory", default="/"),
        ConfigField("use_tls", "Require TLS", kind="boolean", required=False, default=True),
    ),
))
_s(Store(
    key="webdav", label="WebDAV", kind=NATIVE, package="webdavclient3",
    description="Read files from a WebDAV share.",
    extra_fields=(
        ConfigField("base_url", "Base URL", placeholder="https://files.example.com/dav"),
        ConfigField("username", "Username"),
        ConfigField("password", "Password", kind="secret"),
        ConfigField("directory", "Directory", required=False, default="/"),
    ),
))
_s(Store(
    key="dropbox", label="Dropbox", kind=NATIVE, package="dropbox",
    description="Read files from a Dropbox folder.",
    extra_fields=(
        ConfigField("access_token", "Access token", kind="secret"),
        ConfigField("directory", "Folder", required=False, default=""),
    ),
))
_s(Store(
    key="box", label="Box", kind=NATIVE, package="boxsdk",
    description="Read files from a Box folder.",
    extra_fields=(
        ConfigField("access_token", "Access token", kind="secret"),
        ConfigField("folder_id", "Folder id", required=False, default="0"),
    ),
))
_s(Store(
    key="google_drive", label="Google Drive", kind=NATIVE, package="google-api-python-client",
    description="Read files from a Google Drive folder.",
    extra_fields=(
        ConfigField("credentials_json", "Service account JSON", kind="secret"),
        ConfigField("folder_id", "Folder id", required=False),
    ),
))
_s(Store(
    key="onedrive", label="OneDrive / SharePoint", kind=NATIVE, package="msal",
    description="Read files from OneDrive or a SharePoint document library.",
    extra_fields=(
        ConfigField("tenant_id", "Tenant id"),
        ConfigField("client_id", "Client id"),
        ConfigField("client_secret", "Client secret", kind="secret"),
        ConfigField("drive_id", "Drive id", required=False),
        ConfigField("directory", "Folder", required=False, default="/"),
    ),
))


#: The format settings every store shares, so the matrix is literally one
#: connector times one registry.
def format_fields() -> tuple[ConfigField, ...]:
    return (
        ConfigField(
            "format",
            "File format",
            kind="select",
            options=tuple(spec.name for spec in FORMATS),
            default="csv",
            help="What the files hold. Detected from the extension when left alone.",
            required=False,
        ),
        ConfigField(
            "compression",
            "Compression",
            kind="select",
            options=("none", "gzip", "zip"),
            default="none",
            required=False,
        ),
    )


def spec_for(store: Store) -> ConnectorSpec:
    available, reason = store.available()
    if store.kind == S3_COMPATIBLE:
        fields: tuple[ConfigField, ...] = (
            *( (store.endpoint_field,) if store.endpoint_field else () ),
            ConfigField("bucket", "Bucket"),
            ConfigField("prefix", "Prefix", required=False, help="Only look under this key prefix."),
            ConfigField("access_key_id", "Access key id"),
            ConfigField("secret_access_key", "Secret access key", kind="secret"),
            *store.extra_fields,
            *format_fields(),
        )
    else:
        fields = (*store.extra_fields, *format_fields())

    capabilities = (
        {"test", "discover", "schema", "read", "incremental"} if available else {"test"}
    )
    return ConnectorSpec(
        type=store.key,
        label=store.label,
        category="storage",
        description=store.description,
        config_fields=fields,
        capabilities=frozenset(capabilities),
        driver_package=None if (store.kind == S3_COMPATIBLE or store.builtin) else store.package or None,
        documentation_url=store.docs_url,
        available=available,
        unavailable_reason=reason,
        tier=store.tier,
        verified_by=store.verified_by,
        origin="matrix",
    )


def all_stores() -> list[Store]:
    return sorted(TABLE.values(), key=lambda store: store.label.lower())


def combinations() -> int:
    """How many store-and-format pairs the matrix covers.

    Reported rather than claimed: this is the number that changes when a format
    is added, and it is what "one filesystem abstraction times the format
    registry" actually means.
    """
    return len(TABLE) * len(FORMATS)


def matrix() -> dict[str, list[str]]:
    """Every store, and the formats it can read."""
    readable = [spec.name for spec in FORMATS]
    return {store.key: list(readable) for store in all_stores()}
