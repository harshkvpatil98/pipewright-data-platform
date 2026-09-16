"""Turning a manifest into a working connector.

The whole point of Phase 10: this file is written once, and every SaaS
connector after it is a YAML file. What it does is translate a declaration --
where the records are, how the API paginates, which header carries the token --
into the configuration the tested REST client already understands.

It deliberately adds no new HTTP behaviour. Anything a manifest cannot express
is a hand-written connector, because a manifest format that grows until it can
express everything has become a programming language with no debugger.
"""

from __future__ import annotations

from typing import Any

from service_connectors.adapters.rest import RestConnector
from service_connectors.manifest import Manifest, streams_of, to_spec
from service_connectors.protocol import (
    ConnectorError,
    ReadResult,
    StreamColumn,
    StreamRef,
    TestResult,
    with_tier_note,
)

#: How a manifest's declared types map to the names the rest of the platform
#: uses for a column. The lattice does the real work; this is the label.
_COLUMN_TYPES = {
    "STRING": "string",
    "INTEGER": "integer",
    "BIGINT": "integer",
    "FLOAT": "float",
    "DECIMAL": "decimal",
    "BOOLEAN": "boolean",
    "DATE": "date",
    "TIME": "time",
    "TIMESTAMP": "timestamp",
    "JSON": "json",
    "ARRAY": "array",
    "UUID": "uuid",
    "BYTES": "bytes",
}


class ManifestConnector(RestConnector):
    """A REST connector whose vendor-specific answers come from a file."""

    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest
        self.spec = to_spec(manifest)
        self._streams = streams_of(manifest)

    # ---------------------------------------------------------------- shape

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        """The endpoints this manifest declares.

        Declared rather than fetched: these vendors publish a fixed set of
        objects, and asking the API for its own catalogue costs a round trip to
        learn something that does not change between releases.
        """
        return list(self._streams)

    def columns(self, config: dict[str, Any], stream: StreamRef) -> list[StreamColumn]:
        """The columns the vendor documents for this endpoint.

        From the manifest, not from a sample: a sample of an API that returns
        nulls for optional fields describes the sample, not the endpoint.
        """
        declared = self._stream_named(stream.name)
        if not declared.schema_fields:
            raise ConnectorError(
                f"The manifest for {self.spec.label} does not describe the columns of "
                f"'{stream.name}'. Read a page to see what comes back."
            )
        primary = declared.primary_key
        return [
            StreamColumn(
                name=spec.rename or path.split(".")[-1],
                data_type=_COLUMN_TYPES.get(spec.type, "string"),
                nullable=path != primary,
                primary_key=path == primary,
            )
            for path, spec in declared.schema_fields.items()
        ]

    # ------------------------------------------------------------- running

    def test(self, config: dict[str, Any]) -> TestResult:
        result = super().test(self._resolve(config, self._streams[0] if self._streams else None))
        # A working request proves the credential, not the manifest. The caveat
        # is said here so it reaches the connection-test screen, which is where
        # somebody decides whether to trust this source.
        return with_tier_note(result, self.spec)

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef | None = None,
        *,
        limit: int = 10_000,
        cursor: str | None = None,
    ) -> ReadResult:
        resolved = self._resolve(config, stream, cursor=cursor)
        # The stream is already baked into the resolved path, so it is not
        # passed on -- the parent would otherwise use the stream name as a path.
        #
        # Neither is the cursor: `_resolve` has already written it into the
        # request the way this vendor's incremental filter wants it. Passing it
        # on as well would add a second, literal `cursor=` parameter, which is
        # either ignored or a 400 depending on how strict the API is.
        result = super().read(resolved, None, limit=limit)
        return with_tier_note(self._apply_renames(result, stream), self.spec)

    # -------------------------------------------------------------- private

    def _stream_named(self, name: str):
        for stream in self.manifest.streams:
            if stream.name == name:
                return stream
        raise ConnectorError(
            f"{self.spec.label} has no stream called '{name}'. "
            f"Available: {', '.join(s.name for s in self.manifest.streams)}."
        )


    #: Characters that would end one URL component and start another. A config
    #: value is a *piece* of a URL, never a place to build one: without this,
    #: `subdomain = "evil.com/x#"` turns `https://{subdomain}.vendor.com` into a
    #: request to a host the manifest never named, with the credential attached.
    _UNSAFE_IN_URL = frozenset('/\\?#@:%" \t\n\r')

    def _fill(self, template: str, config: dict[str, Any], what: str) -> str:
        """Substitute config values into a URL template, safely.

        Only the settings this template actually names are read. Scanning the
        whole config instead refused every Basic-auth connection in the
        catalogue, because those credentials are email addresses and an `@` is
        not allowed *in a URL component* -- which `auth_username` never is. A
        rule about URL safety has to be applied to the values that end up in
        the URL, or it becomes a rule about which passwords are allowed.
        """
        import string

        names = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        if not names:
            return template

        safe: dict[str, str] = {}
        for key in sorted(names):
            value = config.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ConnectorError(
                    f"{self.spec.label} needs {key} to build its {what}."
                )
            text = str(value)
            offending = sorted(self._UNSAFE_IN_URL & set(text))
            if offending:
                raise ConnectorError(
                    f"{key!r} cannot contain {' '.join(repr(c) for c in offending)}: "
                    f"it is part of the {what} this connector builds, not a place to "
                    "put one."
                )
            safe[key] = text
        return template.format(**safe)

    def _resolve(
        self, config: dict[str, Any], stream: StreamRef | None, *, cursor: str | None = None
    ) -> dict[str, Any]:
        """The manifest and the user's settings, as one REST configuration."""
        manifest = self.manifest
        declared = self._stream_named(stream.name) if stream is not None else manifest.streams[0]

        # Both the address and the path carry placeholders: a subdomain or
        # region in the base URL, an organisation or table name in the path.
        # Substituting only the first left `/repos/{org}/{repo}/issues` to be
        # requested literally.
        base_url = self._fill(manifest.base_url, config, "address")
        path = self._fill(declared.path, config, "path")

        resolved: dict[str, Any] = {
            "base_url": base_url,
            "path": path,
            "records_path": declared.records_path,
            "auth_secret": config.get("auth_secret"),
            "auth_username": config.get("auth_username"),
            "extra_headers": dict(manifest.default_headers),
            "extra_params": dict(declared.params),
            "pagination": declared.pagination.kind,
            "page_size": declared.pagination.page_size,
            "cursor_path": declared.pagination.cursor_path,
            # The vendor's own vocabulary for its pagination parameters. Read
            # from the manifest rather than assumed: `pageToken`, `$skiptoken`
            # and `page[cursor]` are all "the cursor", and sending `cursor`
            # instead gets page one back forever.
            "page_param": declared.pagination.page_param,
            "size_param": declared.pagination.size_param,
            "offset_param": declared.pagination.offset_param,
            "cursor_param": declared.pagination.cursor_param,
            "start_page": declared.pagination.start_page,
            "send_page_size": declared.pagination.send_page_size,
            "timeout_seconds": config.get("timeout_seconds"),
        }
        resolved.update(_auth_config(manifest))

        if cursor and declared.incremental is not None:
            resolved["extra_params"][declared.incremental.param] = (
                declared.incremental.template.format(value=cursor)
            )
        return {key: value for key, value in resolved.items() if value is not None}

    def _apply_renames(self, result: ReadResult, stream: StreamRef | None) -> ReadResult:
        """Give columns the names the manifest says they should have.

        `attributes.email` is where the value is; `email` is what anybody
        building a pipeline wants to type.
        """
        declared = self._stream_named(stream.name) if stream is not None else self.manifest.streams[0]
        renames = {
            path: spec.rename
            for path, spec in declared.schema_fields.items()
            if spec.rename and spec.rename != path
        }
        frame = result.dataframe
        if renames and frame is not None and hasattr(frame, "rename"):
            present = {old: new for old, new in renames.items() if old in getattr(frame, "columns", [])}
            if present:
                result.dataframe = frame.rename(columns=present)
        return result


def _auth_config(manifest: Manifest) -> dict[str, Any]:
    auth = manifest.auth
    if auth.kind == "none":
        return {"auth_method": "none"}
    if auth.kind == "basic":
        return {"auth_method": "basic"}
    if auth.kind == "api_key" and auth.placement == "query":
        return {"auth_method": "api_key_query", "auth_query_name": auth.query_param}
    # Everything else is a header, and the manifest's template says how it reads.
    return {
        "auth_method": "api_key_header",
        "auth_header_name": auth.header,
        "auth_template": auth.template,
    }
