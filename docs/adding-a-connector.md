# Adding a connector

There are four ways, and which one you need depends on what you are
connecting to. None of them involves editing more than one file.

The catalogue today: **211 connectors**, 155 usable on this deployment, 50 verified by a test that actually runs them. 117 come from manifests, 48 from the dialect table, 16 from the object-store matrix, 9 are engines listed with what to use instead, and 21 are hand-written.

---

## 1. A SaaS API — write a manifest

Drop a YAML file in
`services/service-connectors/src/service_connectors/manifests/`. That is the
whole task: no Python, no registration, no frontend change. The file is
validated when the package imports, so a malformed one fails the build rather
than shipping.

```yaml
key: acme_widgets
label: Acme Widgets
category: saas
description: Read widgets and orders from Acme.
docs_url: https://developers.acme.example/reference
base_url: https://api.acme.example/v1
auth:
  kind: api_key
  placement: header
  header: X-Acme-Key
  template: "{token}"
streams:
  - name: widgets
    path: /widgets
    records_path: data
    primary_key: id
    pagination:
      kind: cursor
      cursor_param: cursor
      cursor_path: meta.next
    incremental:
      cursor_field: updated_at
      param: since
      template: "{value}"
    schema:
      id: { type: STRING }
      attributes.name: { type: STRING, rename: name }
      attributes.updated: { type: TIMESTAMP, tz_aware: true, rename: updated_at }
tier: 4
```

Then run the connector tests. They will tell you if anything is wrong:

```bash
pytest services/service-connectors/tests -q
```

### What each field is for

| Field | Required | Notes |
|---|---|---|
| `key` | yes | Lower case identifier. Becomes the connector type in the API. |
| `label` | yes | What a person sees in the picker. |
| `category` | no | Which section of the catalogue it appears in. |
| `description` | yes | One sentence saying what it reads. Shown on the card. |
| `docs_url` | no | The vendor's API reference, linked from the card. |
| `base_url` | yes | The API root. May contain `{placeholders}` filled from config_fields -- a subdomain, a region, an account id. |
| `auth` | no | How the credential is sent. Defaults to a bearer token. |
| `default_headers` | no | Headers every request carries, such as an API version. |
| `rate_limit` | no | How hard to push before backing off. |
| `streams` | yes | The endpoints this connector reads. At least one. |
| `config_fields` | no | Settings beyond the credential -- an account id, a region, a subdomain. Every `{placeholder}` used above needs one. |
| `tier` | no | How verified this is. 4 means never executed here, and is the default. |
| `verified_by` | no | The test file backing a tier above 4. Required for tiers 1-3. |

**Types** a `schema:` block may use: `STRING`, `INTEGER`, `BIGINT`, `FLOAT`, `DECIMAL`, `BOOLEAN`, `DATE`, `TIME`, `TIMESTAMP`, `JSON`, `ARRAY`, `UUID`, `BYTES`.
They name the Phase 08 type lattice, so `TIMESTAMP` means the platform's
timestamp with tz-awareness included — not a hint for something later to
guess at.

**Categories**: `database`, `warehouse`, `api`, `storage`, `saas`, `nosql`, `file`, `timeseries`, `streaming`, `lakehouse`.

### Things the validator will stop you doing

- An unknown key. A typo that silently did nothing is how a connector ships
  looking fine and paginates only the first page.
- Cursor pagination without a `cursor_path`.
- An auth `template` with no `{token}` in it, or an incremental `template`
  with no `{value}`.
- Two streams with the same name.
- A `{placeholder}` in `base_url` or a `path` with no `config_fields` entry
  to fill it — a connector nobody could configure.
- Claiming a tier above 4 without saying what verified it.

A config value used in a URL also cannot contain `/`, `?`, `#`, `@`, `:` or
whitespace. It is a *piece* of a URL, never a place to build one: without
that rule a subdomain setting could move the request to a host the manifest
never named, with the credential attached.

---

## 2. A SQL database — add a row to the dialect table

`services/service-connectors/src/service_connectors/dialects.py`. Six lines:

```python
_d(key="acmedb", label="AcmeDB", driver="acmedb+acmedriver", package="acme-sqlalchemy",
   default_port=6789, limit_style="fetch_first",
   description="Read tables from AcmeDB.")
```

SQLAlchemy does the introspection and the reading, so what a row supplies is
the URL, the driver package, the connection shape (`SERVER`, `FILE` or
`ACCOUNT`) and how the dialect spells "give me a few rows".

If the driver is not installed on a deployment, the connector still appears
and still answers `test()` — with the name of the package to install — and its
capabilities narrow to `test` alone, so nothing promises a read it cannot do.

---

## 3. An object store — add a row to the store table

`services/service-connectors/src/service_connectors/stores.py`. If the store
publishes an S3-compatible endpoint, that is all it takes and the result is
working code:

```python
_s(Store(key="acme_object", label="Acme Object Storage", kind=S3_COMPATIBLE,
         description="Read objects from Acme Object Storage.",
         endpoint_template="https://s3.{region}.acme.example",
         endpoint_field=ConfigField("region", "Region", default="eu-west-1")))
```

Every store reads every format in the registry, so the matrix is 272 store-and-format combinations across 17 formats. Adding a format adds it to every store at once.

---

## 4. An engine nothing here can drive — declare it, with a way out

`services/service-connectors/src/service_connectors/datastores.py`. Cassandra,
Redis, HBase and their neighbours each need a client library and their own
idea of what a row is, so none of them reads anything here yet. They are in
the catalogue anyway, because omitting Cassandra leaves somebody concluding
their data is out of reach — and most of these publish a second interface the
platform *does* read.

```python
_s(DataStore(key="acme_kv", label="Acme KV", category="nosql",
             description="Read records from Acme KV.",
             package="acme-kv-client",
             instead="Acme KV's REST gateway is readable through the REST connector."))
```

`instead` is required and the dataclass refuses an entry without it: a
catalogue entry that cannot do anything and cannot say what would is noise.
Every one of these declares only `test`, reports `available: false`, and
answers a connection test with the reason.

---

## Verification tiers

Every connector carries one, and it is shown wherever a connector is chosen
and in the output of any run that used it.

| Tier | Badge | Meaning |
|---|---|---|
| 1 — Verified | ✅ | Runs against a real instance in CI on every merge. |
| 2 — Tested | ◑ | Runs against a container or local fixture in CI on every merge. |
| 3 — Recorded | ◔ | Tested by replaying a captured real session. Never run live here. |
| 4 — Unverified | ○ | Never executed against a real instance here. The configuration is as the vendor documents it; treat your first run as the real test. |

The default is 4, deliberately: a connector that forgets to say is described
as unverified rather than silently promoted.

**A tier above 4 needs a citation.** `verified_by` names a test file, and
`test_generators.py` checks that the file exists *and* mentions the connector.
Without that the tier system is decoration — anybody could type `tier: 1` and
the badge would read "Verified" on something nothing has ever run.

To promote a connector, write the test first, then cite it:

```yaml
tier: 2
verified_by: test_acme_widgets.py
```

---

## Secrets

A config value can be a secret or a *reference* to one:

```
vault://database/prod#password
env://ACME_API_KEY
file:///run/secrets/acme#api_key
awssm://prod/acme-credentials#api_key
azurekv://my-vault/acme-api-key
```

References are stored as pointers and resolved at the point of use. `env` and
`file` work everywhere; the managed stores register only when their SDK is
installed, and a reference to one that is not configured **fails loudly**
rather than falling back — otherwise "our secrets are in Vault" would be a
sentence nobody could check.

---

## Schema drift

A manifest that declares a `schema:` block is watched: the columns it claims
are compared with what is there, and a difference is graded `breaking`,
`risky` or `compatible` by the same code that grades a dataset's drift. A
manifest with no declared schema has nothing to go stale, and the watch
reports it as unwatchable rather than as fine.

The watch runs over **configured connections**, not over the catalogue: a
manifest is a file and cannot change behind your back, whereas the vendor it
describes changes constantly. `POST /projects/{id}/connectors/watch` runs a
sweep now, and a schedule of type `connector_schema_watch` runs it nightly on
the platform's own scheduler. A change files a drift incident — the same
object a failing quality rule produces, on the same list, with the same
timeline — and a schema that goes back to normal closes it again.

A connection that cannot be read is reported as skipped, with the reason.
Treating "we could not look" as "the columns are gone" would file a
breaking incident every time a VPN dropped.
