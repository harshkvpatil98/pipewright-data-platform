# Pipewright Roadmap v2 — The Studio Era

> **Status:** proposed, not started. Phases 01–07 are complete (see `docs/project-case-study.md`).
> **Written:** 2026-08-21
> **Companion doc:** [`HANDOFF.md`](./HANDOFF.md) — read that first if you are a new session.

---

## The thesis

Pipewright today is a *pipeline platform*: you define steps in a form, and they run on a
schedule. That is table stakes. Every competitor has it.

What no ETL tool has done well is collapse the gap between **the spreadsheet where analysts
actually think** and **the pipeline where engineering actually runs**. Analysts export to
Excel because Excel lets them *see and touch* the data. Engineers hate that export because
it forks the truth. Every ETL vendor has picked a side.

The bet of v2 is that you do not have to pick. A grid that edits like Excel, backed by a
transformation recipe that runs like a pipeline, where every cell edit is a *step* — not a
mutation — is the product that makes the export unnecessary.

Everything in this roadmap serves that bet, in this order of importance:

1. **The Studio must feel like a spreadsheet** and be as fast as one, on millions of rows.
2. **It must connect to everything**, because the data is wherever it already is.
3. **It must push work down to the source**, because pulling 100M rows to filter them is
   the reason "modern ETL" tools get ripped out after a year.
4. **It must never lie** about what it did — the constraint that has governed all seven
   completed phases and does not relax here.

---

## What exists today (verified 2026-08-21)

| Surface | State |
|---|---|
| Services | 22 Python service packages |
| Connectors | 19 declared, **14 usable** on a stock machine, 5 driver-gated |
| Transformation steps | **20** (`ALL_STEP_TYPES`) |
| Studio | 3 files, **1,458 LOC** — a step list + config form + preview. **Not a grid.** |
| Theme | **Dark only.** `globals.css` has no `prefers-color-scheme` and no `data-theme` |
| Write-back | **None.** Data flows out to destinations; nothing edits a source in place |
| Execution | **All in pandas.** No pushdown, no SQL generation |
| Tests | 1,256 Python, 111 web |

The four bolded gaps are the roadmap.

---

## Structure: 4 tracks, 16 phases

Tracks are dependency groups, not calendar quarters. Track A gates everything.

```
TRACK A — Foundations          08 Type system & IR ──┬─→ everything
                               09 Design system ─────┘  (parallel, independent)

TRACK B — Sources at scale     10 Connector factory ──→ 11 Ingestion ──→ 12 Pushdown
                                                                             │
TRACK C — The Studio           13 Grid ──→ 14 Formulas ──→ 15 Write-back ────┤
                                       └─→ 16 Tool library                   │
                                       └─→ 17 SQL IDE & notebook             │
                                                                             ▼
TRACK D — Platform depth       18 Time travel   19 Semantic layer   20 Streaming & CDC
                               21 Collaboration 22 Optimizer        23 Extensibility
```

**Critical path:** 08 → 12 → 13 → 15. Everything else can be built around it.

---

# TRACK A — Foundations

Nothing in Tracks B, C, or D is safe to build before these two land. Phase 08 in particular
is the single highest-leverage piece of work in the whole roadmap: it is the reason pushdown,
write-back, and cross-source joins can be *correct* rather than *usually correct*.

---

## Phase 08 — Canonical type system & relational IR ✅ **COMPLETE**

**Why this first.** Right now a column's type is whatever pandas inferred. That is fine when
everything is pandas. The moment a Postgres `NUMERIC(38,10)` travels through Parquet into
BigQuery, or a MySQL `DATETIME` (no timezone) meets a Snowflake `TIMESTAMP_TZ`, silent
corruption becomes possible — and *silent* is the operative word. Phase 03 already produced
exactly this class of bug once: `postgresql.UUID` on SQLite got NUMERIC affinity and an
all-digit UUID was converted to a float. That bug found 16 model files. A type system is the
structural fix.

**Why an IR.** Pushdown (Phase 12), write-back SQL generation (Phase 15), and the formula
engine (Phase 14) all need to answer "what does this step *mean*, independent of how it runs".
Twenty step types each hand-writing their own SQL is twenty chances to disagree with the
pandas implementation. One IR with two backends is one chance, and it can be tested.

### 08.1 — The type lattice

New package: `packages/shared-python/src/shared_python/types/`.

```python
# Canonical types. Deliberately narrower than "whatever a database offers":
# every source type maps INTO this set, and this set maps OUT to every destination.
class PWType:
    BOOLEAN
    INT8 | INT16 | INT32 | INT64
    UINT8 | UINT16 | UINT32 | UINT64
    FLOAT32 | FLOAT64
    DECIMAL(precision, scale)      # exact; never silently becomes a float
    STRING(max_length | None)
    BYTES
    DATE
    TIME(precision)
    TIMESTAMP(precision, tz_aware: bool)   # tz-awareness is part of the TYPE
    INTERVAL
    UUID
    JSON
    ARRAY(element: PWType)
    STRUCT(fields: dict[str, PWType])
    MAP(key: PWType, value: PWType)
    GEOGRAPHY
    UNKNOWN                        # honest; never guessed into something else
```

**Design decisions:**

- **`DECIMAL` is not a float, ever.** Financial data is the single most common ETL payload
  and `0.1 + 0.2 != 0.3` is not an acceptable failure mode. pandas will hold these as
  `object` dtype containing `decimal.Decimal` where exactness matters.
- **Timezone awareness is part of the type, not a flag beside it.** `TIMESTAMP(tz_aware=False)`
  and `TIMESTAMP(tz_aware=True)` are different types that cannot be compared without an
  explicit conversion step. This is the only way to stop the classic "reports shift by 5 hours
  in winter" bug.
- **`UNKNOWN` exists and is allowed to survive.** A column we cannot type is reported as
  untyped. Guessing it into `STRING` is how a numeric column with one bad row becomes text
  for all downstream time.

### 08.2 — Per-source type mappings

```
packages/shared-python/src/shared_python/types/
  lattice.py       # PWType definitions, equality, widening
  coercion.py      # widen(a, b), can_cast(a, b), cast_loss(a, b)
  mappings/
    postgres.py    mysql.py     sqlite.py    sqlserver.py   oracle.py
    snowflake.py   bigquery.py  redshift.py  databricks.py  duckdb.py
    parquet.py     avro.py      arrow.py     json_schema.py excel.py
    pandas_.py
```

Each mapping is a bidirectional pair, `to_pw()` and `from_pw()`, plus — critically —
a **loss report**:

```python
@dataclass(frozen=True)
class CastLoss:
    kind: Literal["precision", "range", "timezone", "nullability", "unsupported"]
    detail: str            # "NUMERIC(38,10) -> NUMERIC(38,9): 1 decimal place dropped"
    severity: Literal["blocking", "warning"]
```

**Rule: a lossy cast is surfaced before the run, not discovered after.** When a pipeline
targets a destination that cannot hold a column's type, the *validation* fails with the loss
report — the same "check before running" discipline that made Phase 05's chart validation work
("a pie needs one grouping column" beats 900 unreadable slices).

### 08.3 — The relational IR

New package: `services/service-transformations/src/service_transformations/ir/`.

```python
# A small algebra. Every one of the 20 existing steps (and the ~200 in Phase 16)
# compiles into a tree of these.
Scan(source, columns)
Project(input, expressions: dict[str, Expr])      # select + derive, unified
Filter(input, predicate: Expr)
Aggregate(input, group_by: list[Expr], aggregates: dict[str, AggExpr])
Join(left, right, on: Expr, how: inner|left|right|full|cross|semi|anti)
Sort(input, keys: list[SortKey])
Limit(input, n, offset)
Window(input, partition_by, order_by, functions: dict[str, WindowExpr])
Distinct(input, subset)
Unnest(input, column, ordinality)                 # arrays/JSON -> rows
Pivot(input, index, columns, values, agg)
Unpivot(input, id_columns, value_columns)
SetOp(left, right, kind: union|union_all|intersect|except)
Extension(input, name, config)                    # escape hatch: never pushed down
```

Expressions are their own tree (`Column`, `Literal`, `Call`, `Case`, `Cast`), and every
`Call` names a function from a **fixed catalogue** with a declared signature and per-dialect
lowering. This is the same allowlist discipline `expressions.py` already uses for
`derive_column` — extended from "safe to eval" to "portable across engines".

### 08.4 — Two backends, proven equivalent

```python
ir.to_pandas(tree, frames) -> DataFrame        # the existing engine, refactored to consume IR
ir.to_sql(tree, dialect)   -> str              # Phase 12 needs this
```

**The test that makes this trustworthy** — and the reason to do it this way — is the pattern
already proven in Phase 02's `test_matches_engine.py`:

> For every IR tree in a generated corpus, run it through `to_pandas` and through `to_sql`
> against a real SQLite/Postgres/DuckDB, and assert the two result frames are **identical** —
> same rows, same order, same dtypes, same nulls.

Add property-based generation (Hypothesis) over IR trees so the corpus is not just the cases
someone thought of. Any dialect that cannot express a node must *say so* (`Unsupported`), never
approximate it.

### 08.5 — Migration of the existing 20 steps

Each existing step gains a `to_ir()` method. The pandas executor is rewritten to run IR rather
than dispatching on `step_type`. `service-lineage`'s `columns.py` — which today symbolically
executes 20 step types — is rewritten to walk IR instead, which means **it automatically
supports every future step** rather than needing an entry per step. The existing guard
(`KNOWN_STEP_TYPES == ALL_STEP_TYPES`) is replaced by "every step compiles to IR".

### Done when

- [x] `PWType` covers every type produced by the usable connectors
- [x] Round-trip test for every mapping, including timezone-awareness and decimal precision
- [x] Loss report is non-empty for every lossy pair and empty for every safe one
- [x] All 20 steps compile to IR
- [x] Differential test: `to_pandas` ≡ `to_sql` — 61 cases against real SQLite
- [x] `service-lineage` derives columns from IR, proven equal to the per-step version
- [x] All existing tests still pass (1,256 → 1,794)

**Deliberately not done:** the cutover. Both executors run and are proven identical, which
is what the plan above asked for; making the IR the only path is a separate decision.
Likewise `columns.py` is still what the API serves.

**Not available here:** Postgres and DuckDB containers, so the differential test runs
against SQLite only. The dialect compilers for Postgres, MySQL and DuckDB are written and
unit-tested but their generated SQL has not been executed.

**Eight bugs the work surfaced**, every one found by a differential test rather than by
reading code:
1. A join condition compiled to `t1.region = t1.region` — always true, so the join
   silently became a **cartesian product**.
2. `NOT (NULL > 5)` kept the row in pandas and dropped it in SQL: collapsing NULL to false
   *before* negating inverts it. Fixed with real three-valued logic.
3. `SUM` over an all-null group returned **0 in pandas, NULL in SQL**.
4. The backends disagreed on join output columns; pandas' `merge` collapses same-named keys.
5. SQLite rejects parenthesised `SELECT`s around `UNION`.
6. `Extension` config was stringified to stay hashable, turning `["a","b"]` into `"['a', 'b']"`.
7. `drop_null_rows` ignored `how`, so `"all"` deleted rows it should have kept.
8. The IR read `casts` where the step uses `mappings`, and was missing `count_distinct`,
   `first` and `last` entirely.

### Risks

| Risk | Mitigation |
|---|---|
| Rewriting the executor breaks working pipelines | IR path runs behind a flag; both executors run in CI on the same corpus until identical |
| `DECIMAL` in pandas is `object` dtype and slow | Only where exactness is declared; benchmark, and use Arrow-backed decimals where available |
| IR is over-engineered for simple steps | `Extension` node means a step that resists modelling is still expressible — it just never pushes down |

**Effort: large.** This is 3–4 focused sessions and touches every service. It is also the
phase that makes the other fifteen tractable.

---

## Phase 09 — Design system, light mode, and a professional identity ✅ **COMPLETE**

**Why now.** It is independent of everything else, it is fast, and every subsequent UI phase
(13, 14, 16, 17) will otherwise be built twice. Also: today the app has **no light mode at
all**, and half of enterprise users will not adopt a dark-only tool.

### 09.1 — The identity problem

Current tokens are `#070b14` ground with a `#38bdf8 → #6366f1` cyan-to-indigo brand gradient
and a `#4f7df3` accent. That is the default look of every AI-era SaaS dashboard. For a tool
people stare at for eight hours, it is also too saturated in the chrome.

**Principle: quiet chrome, loud data.** The convention that professional tools converge on
(Bloomberg, Figma, Linear, Observable) is that the interface itself is near-neutral and
saturated colour is *reserved for meaning* — state, severity, series. Today Pipewright spends
its colour budget on navigation.

### 09.2 — Proposed palette: graphite & signal

Neutrals carry a **slight green-cyan bias** (not the usual blue) so the greys read as
deliberate and leave the blue end of the spectrum free for data series.

```css
/* LIGHT — bare :root, the complete palette */
--canvas:        #FAFBFA;   /* warm-neutral paper, not pure white */
--surface:       #FFFFFF;
--surface-sunken:#F1F4F3;
--ink:           #12171A;   /* near-black with the same green bias */
--ink-2:         #3F4A4E;
--ink-muted:     #616F74;
--line:          #DDE4E3;
--accent:        #0D7983;   /* deep teal — flow, pipes, water */
--accent-hover:  #095E66;
--copper:        #B15108;   /* the single warm note: highlights, active edits */

/* DARK — redefine ONLY tokens, under both the media query and [data-theme] */
--canvas:        #0D1113;
--surface:       #151A1D;
--surface-sunken:#0A0D0F;
--ink:           #E6EAE9;
--ink-2:         #AAB6B7;
--ink-muted:     #869394;
--line:          #242C2F;
--accent:        #2DD4BF;
--accent-hover:  #5EEAD4;
--copper:        #F59E0B;

/* SEMANTIC — separate axis from the accent, and colourblind-safe */
--ok:      #0F8F63 / #34D399
--warn:    #A86707 / #FBBF24
--danger:  #C2413C / #F87171
--info:    #0369A1 / #38BDF8
```

Semantic colour is **never** the accent, so "this is interactive" and "this is failing" can
never be confused. Every state also carries a non-colour cue (icon, weight, or border) so the
UI survives deuteranopia and greyscale printing.

### 09.3 — The three-state theme problem

This is the part that is easy to get wrong. A viewer has **three** states, not two:

1. Explicit light → `data-theme="light"` on `<html>`
2. Explicit dark → `data-theme="dark"`
3. **System (the default)** → *nothing stamped*, only `prefers-color-scheme` applies

```css
:root { /* complete LIGHT palette — the un-stamped, un-matched default */ }

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { /* dark token overrides */ }
}

:root[data-theme="dark"] { /* dark token overrides again, so the toggle wins */ }
```

**Rule enforced by a lint test:** no component may declare a colour anywhere except through a
token. A colour whose only definition lives inside a media query renders one theme's text on
the other theme's ground — the classic unreadable-app bug.

### 09.4 — Beyond colour

- **Type scale** — a real scale (12/13/14/16/20/24/32/44) with `tabular-nums` everywhere digits
  align. Data grids live or die on numeral alignment.
- **Density modes** — comfortable / compact / dense. An analyst with 40 columns needs dense;
  it is not a nice-to-have, it is the difference between usable and not.
- **Motion** — `prefers-reduced-motion` respected globally; no animation over 200ms in the grid.
- **Focus** — a visible focus ring on every interactive element. The Studio will be keyboard-first
  (Phase 13); invisible focus makes that impossible.
- **Persistence** — theme + density stored per user (`user_preferences` table), not in
  `localStorage` alone, so it follows people across machines. Server-rendered on first paint
  to avoid the white flash.

### 09.5 — Component library

Promote the ad-hoc components in `packages/shared-ui` into a real set with documented props:
`Button` (5 variants × 3 sizes), `Input`, `Select`, `Combobox`, `Checkbox`, `Radio`, `Switch`,
`Slider`, `Tabs`, `Dialog`, `Drawer`, `Popover`, `Tooltip`, `Menu`, `Toast`, `Badge`, `Pill`,
`Table`, `Tree`, `Breadcrumb`, `Skeleton`, `EmptyState`, `CodeBlock`, `DiffView`, `Resizable`,
`SplitPane`, `CommandPalette`.

A Storybook-style gallery page renders every component in every variant in **both themes** at
once, so a regression is visible rather than reported.

### Done — delivered 2026-08-21

- [x] Light, dark, and system all render correctly; verified in a real browser under both OS settings
- [x] Zero colour literals anywhere, including inside Tailwind arbitrary values (enforced by test)
- [x] ~2,860 usages migrated across `apps/web` **and** `packages/shared-ui`
- [x] Density genuinely drives 112 table cells via a `cell-pad` utility
- [x] WCAG AA on all 120 token pairs, AAA for body text — measured, and four light values were
      corrected because they failed
- [x] Preferences persist per user (migration 0026); pre-paint script prevents the flash

**What the numbers actually were:** 1,256 → 1,270 Python tests, 111 → 287 web tests.

**Four bugs the work surfaced**, none of which a unit test would have found:
1. `packages/shared-ui` was missed entirely — the Button and Input on every screen kept
   near-black borders in light mode. Caught by a screenshot, not a test.
2. `rgba(79,70,229)` — the *old* indigo brand accent — survived inside
   `shadow-[0_12px_30px_rgba(...)]` and rendered as a violet halo under the primary button.
3. `disabled:opacity-50` is theme-blind: half-strength bright teal on near-black still reads as
   an active button. Needed `saturate-0` as well.
4. The switch thumb was `#ffffff` on a `--surface-2` track: **1.06:1** in light mode, invisible.

**One correction to the plan above:** forcing every chart series to 3:1 against white is the
wrong constraint — it crushes the palette into one dark band and destroys the separation that
makes it colour-blind safe. Series are distinguished from *each other* and named by a legend.

---

# TRACK B — Sources at scale

Goal: **200+ sources**, from 19. The way to fail at this is to hand-write 200 connectors;
they rot, and nobody can tell which ones actually work. The way to succeed is to build three
generators and hand-write only the ~15 that genuinely resist generation.

---

## Phase 10 — Connector factory: 19 → 200+ ✅ COMPLETE (2026-09-16)

**The leverage already exists.** Phase 04 proved it: Stripe, HubSpot, Shopify, Salesforce and
Google Sheets are ~40 lines each because they are presets over one tested REST connector. That
result generalises. Most of the 200 are not new code — they are new *declarations*.

### 10.1 — Four generation strategies

| Strategy | Mechanism | Yields |
|---|---|---|
| **SQL dialect table** | One SQLAlchemy-backed adapter + a per-database dialect entry (quoting, LIMIT/TOP, date functions, introspection queries, driver package) | ~32 databases |
| **REST manifest** | Declarative YAML per SaaS: base URL, auth, endpoints, pagination, schema, incremental cursor | ~110 SaaS |
| **Object store × format matrix** | One filesystem abstraction × the format registry from Phase 04 | 10 stores × 22 formats |
| **Hand-written** | Genuinely different protocols | ~15 |

### 10.2 — The REST manifest

```yaml
# connectors/manifests/klaviyo.yaml
key: klaviyo
label: Klaviyo
category: marketing
docs_url: https://developers.klaviyo.com/en/reference/api_overview
auth:
  kind: api_key
  placement: header
  header: Authorization
  template: "Klaviyo-API-Key {api_key}"
base_url: https://a.klaviyo.com/api
default_headers: { revision: "2024-10-15" }
rate_limit: { requests_per_second: 10, burst: 75, retry_on: [429], backoff: exponential }
streams:
  - name: profiles
    path: /profiles
    method: GET
    pagination: { kind: cursor, cursor_param: page[cursor], cursor_path: links.next }
    records_path: data
    primary_key: id
    incremental: { cursor_field: attributes.updated, param: filter, template: "greater-than(updated,{value})" }
    schema:
      id: { type: STRING }
      attributes.email: { type: STRING, rename: email }
      attributes.created: { type: TIMESTAMP, tz_aware: true }
```

The manifest is validated against a JSON Schema at build time, so a malformed connector
**cannot ship**. Types reference Phase 08's lattice by name, which is why 08 comes first.

### 10.3 — Verification tiers (the honesty scaling problem)

With 19 connectors, "5 are unverified" is a footnote. With 200, an undifferentiated list is a
lie by omission. Every connector therefore carries a tier, shown in the UI:

| Tier | Meaning | Badge |
|---|---|---|
| **1 — Live-verified** | Runs against a real instance in CI on every merge | ✅ Verified |
| **2 — Container-verified** | Runs against a Docker/WireMock fixture in CI | ◑ Tested |
| **3 — Recorded** | Replays a captured real session; no live credentials | ◔ Recorded |
| **4 — Spec-only** | Written from vendor docs, never executed | ○ Unverified |

Tier 4 connectors are usable but **labelled in the picker, in the config form, and in run
logs**. A run whose source is Tier 4 says so in its output. This is the direct descendant of
the Phase 04 rule that a declared capability is what works *here*, not what was designed.

**Target mix at completion:** ~40 Tier 1–2 (everything self-hostable in a container), ~30
Tier 3, the rest Tier 4 until someone with credentials verifies them.

### 10.4 — The catalogue

**Relational (32)** — PostgreSQL·, MySQL·, MariaDB, SQLite·, SQL Server, Oracle, IBM Db2,
SAP HANA, Sybase ASE, Firebird, Informix, CockroachDB, YugabyteDB, TiDB, Aurora (PG/MySQL),
Cloud SQL, Azure SQL, PlanetScale, Neon, Supabase, DuckDB, ClickHouse, Vertica, Greenplum,
Teradata, Exasol, MonetDB, Netezza, SingleStore, StarRocks, Apache Doris, Trino/Presto

**Warehouses & lakehouses (12)** — Snowflake, BigQuery, Redshift, Databricks SQL, Azure
Synapse, Athena, Dremio, Firebolt, MotherDuck, Rockset, Hive, Impala

**Table formats & catalogues (7)** — Delta Lake, Apache Iceberg, Apache Hudi, Hive Metastore,
AWS Glue Catalog, Unity Catalog, HDFS

**Object storage (10)** — S3·, GCS, Azure Blob, ADLS Gen2, MinIO, Cloudflare R2, Backblaze B2,
DigitalOcean Spaces, Wasabi, Oracle Object Storage

**File transfer (8)** — Local·, SFTP, FTP/FTPS, WebDAV, Dropbox, Box, Google Drive,
OneDrive/SharePoint

**NoSQL, document, graph, search (15)** — MongoDB·, DynamoDB·, Cassandra, ScyllaDB, CouchDB,
Couchbase, Redis, Elasticsearch, OpenSearch, Neo4j, ArangoDB, Firestore, Cosmos DB, HBase,
Aerospike

**Time series (8)** — InfluxDB, TimescaleDB, Prometheus, QuestDB, VictoriaMetrics, Graphite,
OpenTSDB, Amazon Timestream

**Streaming, queues & CDC (13)** — Kafka, Confluent Cloud, Redpanda, Pulsar, Kinesis,
Pub/Sub, Event Hubs, RabbitMQ, NATS, MQTT, SQS, Debezium, native CDC (Postgres logical
replication · MySQL binlog · Mongo change streams) — *see Phase 20*

**API protocols (7)** — REST·, GraphQL·, SOAP, gRPC, OData, JSON:API, inbound webhooks

**File formats (24)** — CSV·, TSV·, PSV, JSON·, JSONL·, XML, XLSX·, XLS, ODS, Parquet·,
Avro·, ORC, Arrow/Feather, fixed-width·, YAML, TOML, INI, Protobuf, MessagePack, HDF5,
SAS7BDAT, SPSS .sav, Stata .dta, DBF, PDF tables, HTML tables, Markdown tables, log formats
(Apache · nginx · syslog · JSON lines)

**SaaS — CRM (10)** — Salesforce·, HubSpot·, Pipedrive, Zoho CRM, Dynamics 365, Freshsales,
Close, Copper, SugarCRM, Insightly

**SaaS — Finance & billing (16)** — Stripe·, QuickBooks, Xero, NetSuite, Sage, Chargebee,
Recurly, Zuora, Braintree, Square, PayPal, Adyen, Bill.com, Expensify, Ramp, Brex

**SaaS — Marketing & advertising (18)** — Google Ads, Meta Ads, LinkedIn Ads, TikTok Ads,
X Ads, Snapchat Ads, Pinterest Ads, Amazon Ads, Microsoft Ads, Criteo, Mailchimp, Klaviyo,
Braze, Marketo, Iterable, SendGrid, Customer.io, ActiveCampaign

**SaaS — Product analytics (11)** — GA4, Adobe Analytics, Mixpanel, Amplitude, Segment, Heap,
PostHog, Pendo, FullStory, Hotjar, Matomo

**SaaS — Support (8)** — Zendesk, Intercom, Freshdesk, ServiceNow, Jira Service Management,
Help Scout, Front, Gorgias

**SaaS — Engineering & project (17)** — Jira, GitHub, GitLab, Bitbucket, Azure DevOps, Linear,
Asana, Monday.com, Notion, Airtable, Confluence, Trello, ClickUp, Shortcut, Sentry, PagerDuty,
Datadog

**SaaS — Commerce (10)** — Shopify·, WooCommerce, Magento, BigCommerce, Amazon Seller Central,
eBay, Etsy, Squarespace, Wix, Faire

**SaaS — HR & payroll (12)** — Workday, BambooHR, Greenhouse, Lever, Gusto, Rippling, ADP,
Namely, Personio, HiBob, SuccessFactors, UKG

**SaaS — Communication & forms (11)** — Slack, Microsoft Teams, Gmail, Outlook/Graph, Twilio,
Zoom, Calendly, Google Calendar, Google Sheets·, Typeform, SurveyMonkey

> `·` = exists today (19 total)  ·  **Grand total ≈ 250 sources**

### 10.5 — Connector operations at this scale

- **Health dashboard** — per-connector last-successful-run, error rate, tier, drift status.
- **Schema evolution watch** — SaaS vendors change APIs constantly. A nightly job re-discovers
  each connector's schema and files a drift incident (reusing Phase 02 machinery) rather than
  letting a pipeline break at 3am.
- **Secrets** — a real vault abstraction (env → HashiCorp Vault / AWS Secrets Manager / Azure
  Key Vault), never plaintext config. OAuth refresh tokens rotated automatically.
- **Connector SDK for customers** — publish the manifest schema and the conformance suite so a
  company can add its own internal system. This is what makes 250 become 2,500.

### Done when

- [x] Manifest schema published; a malformed manifest fails the build
- [x] All three generators produce connectors that pass the existing conformance suite unchanged
- [x] Tier is displayed everywhere a connector is chosen, and in run output
- [x] ≥ 40 connectors at Tier 1–2 with containerised CI — **50**
- [x] Adding a documented REST SaaS takes < 30 minutes end to end

**Effort: very large, but highly parallel.** The generators are ~2 sessions; the manifests are
mechanical and can be produced in batches by category.

### What shipped

**211 connectors**, 155 usable on this machine, **50 at tier 2** and the other 161
honestly at tier 4. Four generators, not three: manifests (117), the dialect table
(48), the object-store matrix (16), and a fourth for engines this platform cannot
drive yet (9) — each of which names the interface it *can* read instead, because
omitting Cassandra leaves somebody concluding their data is out of reach while
listing it as working would be worse.

**The tier is the phase.** Two hundred connectors without one is a lie by omission,
and a tier nobody can audit is decoration. So `verified_by` names a test file, a
test resolves the citation and checks the file actually drives that connector, and
`ConnectorSpec.__post_init__` refuses a tier above 4 with no citation. Three
things earn the fifty:

- **`test_vendor_contracts.py` — 34 SaaS manifests.** Each contract states, from the
  vendor's reference and independently of the shipped manifest, where the records
  sit, how the next page is pointed at, what that pointer is called, which fields a
  record carries and how the credential travels. The harness cross-checks the
  manifest against it *and* runs the real `ManifestConnector` against a loopback
  server that answers that way — two pages, so pagination has to actually advance.
- **`test_containers.py` — PostgreSQL, MySQL, MariaDB.** Real servers in real
  containers, wired into `ci.yml` as service containers with a pre-flight check
  that fails the build if they are missing, because a skipped test is a green
  build and the badge would be resting on nothing. `docker-compose.connectors.yml`
  is the same thing for a laptop.
- **`test_generators.py` — the S3 family and the store matrix.** Parametrised over
  every S3-compatible store rather than the one somebody happened to write a test
  for: each one's endpoint template, listing and read through the format registry.

Nine PostgreSQL-wire dialects — CockroachDB, YugabyteDB, Greenplum, Neon, Supabase,
Cloud SQL, Aurora, TimescaleDB, QuestDB — execute the exact code path
`test_containers.py` exercises and are **deliberately not promoted**. "CockroachDB
works" and "the PostgreSQL driver works" are different claims, and a test pins the
distinction so nobody quietly closes it.

**Two protocol connectors rather than two more manifests.** OData and JSON:API each
specify the envelope, so one connector reads every service that implements it —
every Dynamics, Business Central or SAP Gateway feed, every Ember or Rails API.
OData's `discover` genuinely discovers, from the service document.

**10.5 shipped whole.** The health view answers "what could this deployment reach"
with no database, including which single package would unlock the most. The schema
watch (`sweep.py`, migration 0029) walks a project's connections, remembers what it
saw and files a **drift incident** through Phase 02 — recurrences collapse onto one
incident by fingerprint, a schema that steadies closes it, and a source that cannot
be read is reported as skipped rather than as a missing column, because otherwise a
dropped VPN files a breaking incident. It runs on the platform's own scheduler as a
`connector_schema_watch` schedule rather than a second cron nobody watches. Secrets
can be references — `vault://database/prod#password` — resolved at the point of use
with no fallback to plaintext, deliberately.

### Five bugs this phase's own tests found

The verification was not ceremony; every one of these was live in the catalogue.

1. **Manifest pagination parameter names were read and then dropped.** `rest.py`
   hard-coded `page`/`cursor`, so every manifest declaring `page[cursor]`,
   `pageToken`, `$skiptoken` or `starting_after` — 37 of them — asked for page one
   again and collected the same rows until `MAX_PAGES`. A row count never shows it.
2. **Seven manifests treated a next-page *URL* as a token.** Zendesk, Klaviyo,
   Bitbucket, Front, PostHog, Confluence and Recurly all return an address in the
   body. Now a `next_url` strategy, with a same-origin guard: the credential is in
   a header, and following a link to another host hands it over.
3. **`httpx` `params=` replaces a URL's query rather than adding to it**, so an
   empty dict threw away the page marker on every `Link`-header follow-up.
4. **The hand-written SQL connector's `read()` had never worked** — `query=` where
   the function takes `sql=`. Only a real database surfaced it.
5. **A Basic-auth username could not contain `@`.** The URL-safety check scanned
   the whole config instead of the placeholders the template names, so every
   Basic-auth connection in the catalogue — Zendesk, Jira, Bitbucket — was
   unconfigurable with the email address those vendors issue.

Two more came out of the review rather than a test: the new watch routes did not
assert project access (the gateway guard defers to the service by design, so
"no access" reads as "not found"), and snapshots were keyed on a bare stream name,
so `public.orders` and `analytics.orders` were compared against each other.

### Deliberately not done

- **Streaming, queues and CDC (13 sources).** The catalogue above already says
  *see Phase 20*; Kafka and friends are a different execution model, not another
  declaration.
- **Inbound webhooks and gRPC.** A webhook is a receiver, not a puller — it needs
  an endpoint, a store and a replay story, which is Phase 20's shape. gRPC needs
  `grpcio` and reflection-based dynamic clients, which is a connector's worth of
  work on its own.
- **Tier 3 is empty, and stays empty.** "Recorded" means replaying a *captured real
  session*, and no credentials exist on this machine for any of these vendors.
  Fabricating a recording and calling it a capture would be the exact failure the
  tier system was built to prevent, so the tier is declared, documented, shown in
  the health view at zero, and left alone.

---

## Phase 11 — Ingestion intelligence: upload anything, understand it ✅ COMPLETE (2026-09-16)

**The ask:** a user uploads a file — Excel, CSV, JSON, a `.sql` dump — and it *works*, with
transformations appropriate to what it actually is.

**The problem:** file ingestion is where every ETL tool is quietly terrible. A CSV is not a
format, it is a rumour. Semicolon delimiters, Latin-1 encoding, a four-line preamble before the
header, `1.234,56` decimals, merged Excel cells, dates as `03/04/2026` (which month is that?).
Getting this right is unglamorous and is the difference between "it just worked" and "I gave up".

### 11.1 — The sniffing pipeline

```
upload → detect container → detect format → detect encoding → detect structure
       → infer types → propose corrections → preview → confirm → materialise
```

Each stage reports **confidence and evidence**, never a silent guess:

- **Container** — plain, gzip, bzip2, xz, zip, tar, 7z. Multi-file archives become multiple
  datasets, or one union if schemas match (offered, not assumed).
- **Encoding** — BOM first, then statistical detection. Report the confidence; if it is low,
  show the bytes that made it ambiguous.
- **Delimiter** — frequency-consistency across lines, not just the first line. Handles quoted
  delimiters, escaped quotes, embedded newlines.
- **Header row** — files with preambles are the norm in finance. Detect by finding the first
  row where the type profile of subsequent rows becomes stable.
- **Decimal & thousands separators** — `1.234,56` vs `1,234.56` decided per column, not per file.
- **Date formats** — the killer. `03/04/2026` is ambiguous; scan the whole column for a value
  that disambiguates (a day > 12). If none exists, **ask**, with the ambiguity shown. Never
  default to US format silently.
- **Type inference** — into Phase 08's lattice, with a per-column sample of the values that
  did not fit, so "this column is 99.8% integer" comes with the 0.2%.

### 11.2 — Per-format handling

| Format | The specific hard part |
|---|---|
| **Excel** | Multiple sheets · merged cells · formulas (value vs formula) · hidden rows/columns · pivot caches · dates as serial numbers · `#REF!` errors · multiple tables on one sheet |
| **CSV family** | Everything in 11.1 · ragged rows · trailing delimiters · null tokens (`NULL`/`NA`/`-`/`""`) |
| **JSON** | Nested objects · arrays needing explode · heterogeneous records · deep paths · JSON-lines vs one big array vs concatenated |
| **XML** | Namespaces · attributes vs elements · repeated elements → rows · XSD when present |
| **`.sql` dump** | Parse `CREATE TABLE` for real schema (better than inference!) · `INSERT` batches · multiple tables · dialect detection · **never execute** the file |
| **Parquet/Avro/ORC** | Schema is embedded — use it, do not infer · nested types map to STRUCT/ARRAY · row groups for chunking |
| **PDF** | Table extraction with explicit confidence; ruled tables reliably, whitespace-aligned tables offered for review |
| **Fixed-width** | Column boundary detection from character-frequency valleys |
| **Statistical (SAS/SPSS/Stata)** | Value labels and variable labels are metadata worth keeping, not discarding |

### 11.3 — The upload experience

- Drag-drop, paste-from-clipboard (paste an Excel range directly into the grid), URL fetch,
  and connector-based pull all converge on the **same** ingestion pipeline.
- Chunked resumable upload for large files; a 2GB CSV must not fail at 95%.
- **Preview before commit** — the first 1,000 rows rendered in the Studio grid with every
  inferred decision editable *before* anything is stored. Change the date format, see it apply.
- **Every decision reversible and recorded.** The inference result is stored as an explicit
  `ingest_spec`, so re-uploading next month's file reuses last month's decisions.

### 11.4 — Nested and semi-structured data

JSON and XML need operations tabular sources do not have — this is the concrete answer to
"every source will have a different set of transformations":

`flatten` (nested object → prefixed columns) · `explode` / `unnest` (array → rows) ·
`json_extract` (JSONPath) · `collect` (rows → array, the inverse) · `infer_json_schema` ·
`normalise` (one document → several related tables, with generated keys)

### Done when

- [x] A corpus of ~60 deliberately awful real-world files ingests correctly, each as a test — **72**
- [x] Ambiguous dates are **asked about**, never assumed — with a test proving it
- [x] `.sql` dumps yield the declared schema, not an inferred one
- [x] A 2GB CSV uploads, resumes after an interruption, and profiles without exhausting memory
- [x] Re-uploading a file reuses the stored `ingest_spec`

**Effort: large.** 3 sessions. Mostly test corpus construction, which is also its value.

### What shipped

`service-ingestion` went from 823 lines to a sniffing pipeline, ten readers, a
spec, a resumable upload and a streaming profiler. The old `parse_tabular_file`
signature is unchanged, so every existing caller still holds; what changed is
everything behind it.

**Nothing guesses silently.** Every stage returns a `Finding` — the answer, a
confidence, and the evidence it decided from. `Certainty.AMBIGUOUS` is a real
state with a real consequence: the finding is `blocking`, the upload is
**refused**, and the API returns both readings in words. `03/04/2026` comes back
as "3 April 2026 or 4 March 2026… the file does not say which", and the scan for
a disambiguating value runs over the *whole* column rather than a sample,
because the one row that settles a thousand can be row nine hundred.

**Every decision is written down.** An `IngestSpec` records the container,
format, delimiter, encoding, header row and each column's type, date format and
decimal separator. The upload screen shows it against real rows before anything
is stored; the confirmed version is what imports; it is kept on the dataset so
"why is this column text" has an answer; and it is saved against the file's
**column fingerprint** so next month's file reads the same way. That last part
is not convenience — inference depends on the data, so a column that read as
day-first in January because one row said `15/01` is genuinely ambiguous in
February when no row does. A recorded decision does not drift.

**Ten readers, each for one format's specific difficulty.** Delimited text
(ragged rows counted and reported rather than dropped or fatal); Excel (merged
cells filled across their range, cached values not formulas, `#REF!` counted,
serial dates converted with the 1899-12-30 epoch that absorbs Lotus's leap-year
bug, other sheets reported); the three things people mean by a JSON file
including concatenated documents, with the records path found rather than
assumed; XML with the record element discovered and DOCTYPEs refused outright
(billion laughs); SQL dumps **parsed, never executed**, yielding `decimal(12,2)`
where inference would have said float; Parquet, Avro and ORC using their
embedded schema; fixed-width with boundaries from character-frequency valleys;
SAS and Stata keeping their variable and value labels.

**A 2GB CSV.** Uploads become sessions: fixed-size chunks addressed by index, so
a retry replaces rather than appends and resuming is the ordinary path with the
received chunks skipped. The whole file is checksummed on assembly, because a
dataset that is 99.97% of a file is worse than a failed upload. Above 64MB the
profile streams — Welford for a numerically stable mean and variance, distinct
counts exact to a ceiling and reported as a bound past it, and duplicate
detection *not attempted* rather than approximated.

**Six nested-data tools** on the Phase 16 registry: flatten, explode,
json_extract, collect, infer_json_schema and normalise. Each is an `Extension`,
honestly outside the algebra and never pushed down. `flatten` and `normalise`
take an explicit field list rather than discovering one, because a tool whose
output columns depend on the rows cannot be predicted by lineage — and lineage
that quietly reports the wrong columns is worse than a tool that asks.
`infer_json_schema` exists to produce that list.

### Seven bugs the corpus and the end-to-end run found

1. **Every import was silently truncated to 5,000 rows.** The analysis sample
   leaked into the materialisation path. The load succeeded, the table looked
   entirely reasonable, and three quarters of a large file was missing. `limit`
   is now explicit with no safe default.
2. **An `.xlsx` was being unwrapped as a zip**, because it is one. Office and
   OpenDocument layouts are now recognised and left alone.
3. **`10.0` was narrowed to an integer.** A value *written* with a decimal point
   is a decimal even when round; narrowing a price column drops the cents.
4. **`01234` became 1234.** A leading zero means a postcode, an account number
   or a SKU — and unlike most inference mistakes this one is invisible.
5. **A UTF-16 BOM survived into the first column name**, giving a column called
   `\ufeffid` that no filter could ever match.
6. **A file with as many preamble lines as data rows** made the modal line width
   a tie, and the tie broke towards the preamble — so the preamble became the
   table and every column was lost. Two places had the same bug.
7. **A header with no rows under it** was read as a row of data, losing the
   column names and inventing a row the file did not have.

### Deliberately not done

- **PDF table extraction.** Needs a layout engine (camelot or pdfplumber) that
  is not installed. The format detector refuses `.pdf` by name with that
  sentence rather than failing obscurely somewhere inside a parser.
- **SPSS `.sav`** needs `pyreadstat`; **`.ods`** needs `odfpy`; **7-Zip** needs
  `py7zr`. Each is declared and refused with the package to install. SAS and
  Stata, which pandas reads natively, are supported.
- **Paste-from-clipboard into the grid.** The pipeline it would converge on is
  built and the endpoint is the same one; what is missing is a grid paste
  handler, which belongs with the Studio rather than with ingestion.

---

## Phase 12 — Pushdown planner & SQL dialect compiler ✅ **COMPLETE**

**Why this is the phase that decides whether Pipewright is a toy.** Today every transformation
runs in pandas, which means every run pulls the whole table over the network into memory. That
works to about 5 million rows and then stops working. Meanwhile the source database — which has
indexes, statistics, and 30 years of query optimisation — sits idle.

**The fix:** run in the source whatever the source can do, and only pull what remains.

### 12.1 — Execution surfaces

Each connector declares what it can execute natively:

```python
class ExecutionSurface(Enum):
    SQL_FULL      # a real SQL database: everything but Extension nodes
    SQL_LIMITED   # SQL-ish, missing windows or CTEs (e.g. older MySQL)
    QUERY_API     # filter/limit/sort only, via query params (most REST SaaS)
    COLUMNAR_FILE # Parquet/ORC: predicate & projection pushdown, no joins
    NONE          # read it all, transform locally (CSV, most APIs)
```

Then per-dialect capability flags: window functions, CTEs, `QUALIFY`, `LATERAL`, `ARRAY_AGG`,
regex, `MERGE`, upsert syntax, transactional DDL, max identifier length, reserved words.

### 12.2 — The split

```python
def plan(tree: IRNode, surface: SourceSurface) -> ExecutionPlan:
    """Split the IR into the part the source runs and the part we run.

    Longest-pushable-prefix from the leaves up: walk the tree bottom-up while
    every node is expressible in the dialect; the first node that is not becomes
    the boundary. Everything below it becomes one SQL query; everything above
    runs in pandas on the result.
    """
```

**Beyond the longest prefix — the cost decisions that actually matter:**

- **Filters are always worth pushing**, even out of order, because they shrink the transfer.
  A `Filter` above a non-pushable node is split and the pushable conjuncts sink below it.
- **Projections are always worth pushing.** Never `SELECT *` when 6 of 200 columns are used.
- **Aggregations are usually worth pushing** — a `GROUP BY` returning 100 rows from 100M is the
  single biggest win available.
- **Sorts are conditional.** A sort the database can serve from an index is free; a sort
  requiring a disk spill may be better done locally on an already-reduced set.
- **Joins push only when both sides live in the same source.** Cross-source joins are the
  local engine's job (Phase 22 adds a smarter federated strategy).
- **Limits push, but never above a non-deterministic node.** `LIMIT` before a local `Sort`
  returns the wrong rows — a subtle correctness bug worth a dedicated test.

### 12.3 — The dialect compiler

```
ir/dialects/
  base.py        # the SQL generator; everything else overrides
  postgres.py  mysql.py  sqlite.py  sqlserver.py  oracle.py  duckdb.py
  snowflake.py bigquery.py redshift.py databricks.py clickhouse.py trino.py
```

The differences that bite: identifier quoting (`"x"` / `` `x` `` / `[x]`), `LIMIT n` vs
`TOP n` vs `FETCH FIRST n ROWS ONLY`, string concat (`||` vs `CONCAT`), date arithmetic (every
single database differs), `NULL` sort order, boolean representation, case sensitivity of
unquoted identifiers, and `MERGE`/upsert syntax.

**Rule: a dialect that cannot express a node raises `Unsupported` and the planner puts the
node on the local side.** It never emits approximate SQL. This is the same rule as Phase 04's
capability declarations, applied to query generation.

### 12.4 — Correctness, which is the whole point

Pushdown is a rewrite of the user's computation. The test bar is therefore absolute:

> **Every IR tree in the corpus, executed via pushdown, must produce a frame byte-identical
> to the same tree executed locally.** Same rows, same order, same nulls, same dtypes.

This runs against real containerised Postgres, MySQL, SQLite, DuckDB and ClickHouse in CI, over
a Hypothesis-generated corpus, and it is the gate on the whole phase. Known divergence traps to
test explicitly: `NULL` ordering, empty-string vs `NULL` (Oracle!), integer division, float
formatting, collation-dependent string comparison, and timezone conversion at DST boundaries.

### 12.5 — Visible to the user

An **execution plan panel** in the Studio, showing what ran where:

```
▼ pushed to postgres://analytics (4 steps, 12.4M → 8,432 rows)
    SELECT region, SUM(amount) AS total ...
    WHERE order_date >= '2026-01-01' GROUP BY region
▼ ran locally (2 steps, 8,432 rows)
    derive_column margin_pct
    sort_rows by margin_pct desc
```

Plus a **"why not pushed?"** explanation on every local step, because the most valuable thing
an optimiser can tell you is what stopped it.

### Done — delivered 2026-08-22

- [x] Differential test: a planned execution equals a local one for every tree in the corpus,
      including trees where the boundary falls mid-pipeline
- [x] Data-reduction tests: a filter transfers only matching rows, an aggregate transfers
      groups not rows, a projection transfers only the columns used
- [x] Every dialect either compiles a node or declares it unsupported — never approximates
- [x] The plan panel shows the split and explains **every** local step
- [x] Execution surfaces declared per source; an unknown source is local-only

**Deliberately not done:** wiring `execute_plan` into real extraction runs. The planner,
the executor and the panel all work and are proven, but the preview still runs locally and
the panel says "*would* run in postgres" rather than claiming it did. Making runs actually
push down is a change to the extraction service, not to this phase's machinery.

**Not available here:** containerised Postgres, MySQL and DuckDB, so the differential test
runs against SQLite. `EXPLAIN` surfacing needs a live connection and is unbuilt.

**The bug the phase surfaced** was in the grid, not the planner: a React state updater read
`event.currentTarget` inside `setViewport`, which React calls during its reducer phase — by
which time the synthetic event is nullified. It unmounted the grid mid-scroll on a
41-column table and left a 5-column one working, which is the worst way to find anything.
`no-pooled-events.test.ts` now guards the whole class.

---

# TRACK C — The Studio

The flagship. Everything above exists to make this possible; everything below exists to make
it enterprise-grade. If only one track ships, it should be this one.

**The governing architectural decision, which everything else follows from:**

> **The grid is a view of a recipe, never a mutable table.** Every edit — typing in a cell,
> adding a column, deleting rows — appends a *step*. The grid renders the result of replaying
> those steps. Nothing is mutated in place.

This single choice gives, for free: infinite undo, complete lineage, reproducibility,
diffability, review-before-apply, and the ability to replay the same recipe on next month's
file. It is also what makes write-back (Phase 15) safe — the diff to compile into SQL is
already materialised as a list of intentions, rather than reverse-engineered from a mutated
table.

---

## Phase 13 — The data grid ✅ **COMPLETE**

Today's Studio is a step list with a preview table. This replaces it with a spreadsheet.

### 13.1 — Rendering architecture

**Canvas-rendered cells with a DOM overlay.** DOM-per-cell dies at ~10,000 visible cells;
the grid must stay at 60fps with 200 columns while scrolling. Canvas draws the cells; a small
DOM layer holds the active editor, the selection outline, and the accessibility tree, so
keyboard navigation and screen readers still work.

- **Two-axis virtualisation** — only visible rows *and* columns are drawn.
- **Windowed data** — rows fetched in pages of 1,000 with an LRU cache and prefetch in the
  scroll direction. Scrolling to row 4,000,000 is a seek, not a load.
- **Frozen panes** — freeze rows and columns independently, like Excel.
- **Column virtualisation with sticky row headers** so a 500-column dataset is navigable.

### 13.2 — Interaction: it must feel like Excel or it has failed

- **Selection** — cell, range, multi-range (Ctrl+drag), whole row, whole column, select-all;
  Shift+arrows to extend; Ctrl+Shift+arrows to jump to the data edge.
- **Fill handle** — drag to fill, with pattern detection (1,2,3… / Jan,Feb,Mar… / dates /
  formulas with relative references). Double-click to fill to the bottom of the data.
- **Clipboard** — copy/paste as TSV so it round-trips with Excel and Google Sheets. Paste a
  range from Excel directly into the grid and it becomes a dataset.
- **In-cell editing** — type to replace, F2 to edit, Escape to cancel, Enter/Tab to commit
  and move, Alt+Enter for a newline.
- **Column operations by direct manipulation** — drag to reorder, drag the edge to resize,
  double-click the edge to autofit, right-click for the full context menu.
- **Full keyboard model** — every Excel keybinding people have in muscle memory, plus a
  command palette (Ctrl+K) that exposes all ~400 tools by name.
- **Sort and filter in the header** — click to sort, a filter chip per column with a value
  list and a search box, exactly like an Excel autofilter. Each becomes a step.

### 13.3 — Making the data legible

- **Column type indicator** in the header, click to change (becomes a `cast` step).
- **Data quality bar** under each header: a stacked micro-bar of valid / null / invalid,
  clickable to filter to the bad rows.
- **Column profile popover** — distribution sparkline, min/max/mean/median, distinct count,
  top values, null %, computed server-side over the full column, not the visible page.
- **Conditional formatting** — colour scales, data bars, icon sets, rule-based highlighting.
- **Cell-level provenance** — click any cell and see which step produced its value, tracing
  back to the source. This is Phase 02's lineage brought down to cell granularity.
- **Diff mode** — show the grid as changed-vs-original, with modified cells highlighted and
  a per-cell before/after on hover.

### 13.4 — The step panel, redesigned

The recipe stays visible beside the grid: reorderable, individually disable-able, with a
per-step row-count delta (`12,400 → 9,881, −2,519`) so the effect of each step is legible.
Click a step to see the grid *as of* that step — time-travel through your own recipe.

### Done — delivered 2026-08-22

- [x] Canvas rendering with two-axis virtualisation; a million-row render commits **under 50
      DOM elements**, and the hot paths are proven independent of dataset size
- [x] Copy/paste is Excel TSV, with quoting, embedded tabs/newlines and tiling
- [x] Every operation reachable by keyboard; focus visible
- [x] Fill handle detects numeric runs and repeats otherwise
- [x] Grid geometry, selection, clipboard, profiling and column state are **pure and tested**
      — 219 tests, no DOM
- [x] Column type glyphs read Phase 08's canonical types, quality bars, profile popover
- [x] Header sort (as a step), autofit, freeze, drag-reorder
- [x] Per-step row/column deltas, collected from the pass that already ran

**Deliberately not done:** cell editing. `onEditCell` and `pasteWrites` exist and are tested,
but the Studio does not enable them — changing one cell needs row identity to say *which* row
changed, and that is Phase 15. Cell-level provenance and diff mode need the same foundation.
Conditional formatting is a formatting concern and belongs with the Phase 16 column tools.

**Not proven:** 60fps at 1,000,000 rows in a real browser. The Studio's preview returns a
fixed sample, so the grid has never been fed more than that end to end; server-side paging is
unbuilt. What *is* proven is that neither React nor the geometry does per-row work.

**Four bugs the work surfaced:**
1. **The grid rendered completely blank** while the status bar reported "3 rows". The empty
   state renders a different tree on first paint, so `useRef` + `[]`-dependency effects
   measured `null` once and never again; the canvas kept its default 300x150.
2. **Profiling read the whole dataset per render** — O(rows x columns), twenty million reads
   at a million rows. Now capped at a stated sample.
3. **The grid vanished whenever a step was incomplete.** Steps are added before they are
   configured, so this happened on every single "add step".
4. My own colour-lint guard caught hardcoded `#ffffff` fallbacks in the canvas palette. A
   plausible light grid on a dark page reads as a design choice, not a bug — it now refuses
   to draw instead.

---

## Phase 14 — The formula engine ✅ **COMPLETE**

**The ask:** calculations, in the grid, the way an analyst already knows how to write them.

`derive_column` today uses an AST-allowlist evaluator in `expressions.py`. That is the right
foundation and the right security posture; this phase grows it into a real formula language.

### 14.1 — The language

```
=IF([amount] > 1000, "large", "small")
=VLOOKUP([sku], products, "price", exact)
=SUMIFS([revenue], [region], "EU", [date], ">=2026-01-01")
=REGEXEXTRACT([email], "@(.+)$")
=DATEDIF([start], [end], "months")
=[revenue] / SUM([revenue]) OVER (PARTITION BY [region])
```

**Two addressing modes, deliberately:**

- **Column references** `[column_name]` — the primary mode. Row-relative by default, which is
  what a column formula means: "for each row".
- **Cell references** `A1`/`$A$1` — supported for people pasting formulas out of Excel, but
  discouraged in the UI, because absolute positional references are exactly what makes
  spreadsheets unmaintainable. Pasting an A1 formula offers to rewrite it in column form.

### 14.2 — Function catalogue (~250)

**Math & trig (40)** — ABS CEILING FLOOR ROUND ROUNDUP ROUNDDOWN MROUND TRUNC INT SIGN MOD
POWER SQRT EXP LN LOG LOG10 FACT COMBIN PERMUT GCD LCM SUM SUMPRODUCT PRODUCT QUOTIENT
SIN COS TAN ASIN ACOS ATAN ATAN2 SINH COSH TANH DEGREES RADIANS PI RAND RANDBETWEEN

**Statistical (45)** — AVERAGE MEDIAN MODE MIN MAX COUNT COUNTA COUNTBLANK COUNTIF COUNTIFS
STDEV STDEVP VAR VARP PERCENTILE QUARTILE RANK PERCENTRANK LARGE SMALL CORREL COVAR SLOPE
INTERCEPT RSQ FORECAST TREND GROWTH LINEST NORMDIST NORMINV TDIST CHIDIST FDIST CONFIDENCE
SKEW KURT GEOMEAN HARMEAN TRIMMEAN AVERAGEIF AVERAGEIFS MAXIFS MINIFS ZTEST

**Text (48)** — CONCAT CONCATENATE TEXTJOIN LEFT RIGHT MID LEN FIND SEARCH SUBSTITUTE REPLACE
TRIM CLEAN UPPER LOWER PROPER TEXT VALUE REPT CHAR CODE UNICODE EXACT SPLIT TEXTBEFORE
TEXTAFTER TEXTSPLIT PAD LPAD RPAD REGEXMATCH REGEXEXTRACT REGEXREPLACE REGEXSPLIT SLUGIFY
INITCAPS TITLECASE SNAKECASE CAMELCASE KEBABCASE NORMALIZE TRANSLITERATE STRIPACCENTS
LEVENSHTEIN JARO SOUNDEX METAPHONE SIMILARITY

**Date & time (46)** — TODAY NOW DATE TIME YEAR MONTH DAY HOUR MINUTE SECOND WEEKDAY WEEKNUM
ISOWEEKNUM QUARTER DATEDIF DATEADD DATESUB EDATE EOMONTH BOM WORKDAY NETWORKDAYS
NETWORKDAYS_INTL YEARFRAC DAYS DAYS360 DATEVALUE TIMEVALUE TEXT_TO_DATE DATE_TRUNC DATE_PART
DATE_FORMAT TO_UTC FROM_UTC TZ_CONVERT AGE FISCAL_YEAR FISCAL_QUARTER FISCAL_PERIOD
IS_WEEKEND IS_HOLIDAY NEXT_BUSINESS_DAY PREV_BUSINESS_DAY DURATION EPOCH FROM_EPOCH

**Logical (18)** — IF IFS IFERROR IFNA IFBLANK SWITCH AND OR NOT XOR TRUE FALSE
COALESCE NULLIF GREATEST LEAST BETWEEN IN

**Lookup & reference (20)** — VLOOKUP HLOOKUP XLOOKUP LOOKUP INDEX MATCH XMATCH OFFSET INDIRECT
CHOOSE ROW COLUMN ROWS COLUMNS TRANSPOSE UNIQUE FILTER SORTBY FIRST LAST

**Financial (26)** — PV FV NPV IRR XIRR XNPV PMT IPMT PPMT RATE NPER SLN SYD DB DDB VDB
ACCRINT DISC YIELD PRICE DURATION MDURATION EFFECT NOMINAL CUMIPMT CUMPRINC

**Type & information (18)** — ISBLANK ISNUMBER ISTEXT ISDATE ISERROR ISNA ISLOGICAL ISNULL
TYPE N T TO_NUMBER TO_TEXT TO_DATE TO_BOOL CAST INFER_TYPE NA

**Aggregate & window (24)** — SUM AVG COUNT MIN MAX over `OVER (PARTITION BY … ORDER BY …)`,
plus ROW_NUMBER RANK DENSE_RANK NTILE LAG LEAD FIRST_VALUE LAST_VALUE NTH_VALUE
CUMSUM CUMPROD CUMMAX CUMMIN RUNNING_TOTAL MOVING_AVG PCT_OF_TOTAL PCT_CHANGE DIFF

**Encoding & security (12)** — MD5 SHA1 SHA256 SHA512 HMAC BASE64ENCODE BASE64DECODE URLENCODE
URLDECODE HTMLESCAPE MASK REDACT

**JSON & nested (14)** — JSON_EXTRACT JSON_PATH JSON_KEYS JSON_VALUES JSON_TYPE JSON_ARRAY
JSON_OBJECT PARSE_JSON TO_JSON ARRAY_LENGTH ARRAY_GET ARRAY_SLICE ARRAY_CONTAINS FLATTEN

**Geospatial (14)** — LAT LON DISTANCE HAVERSINE BEARING WITHIN_RADIUS GEOCODE REVERSE_GEOCODE
POINT_IN_POLYGON BOUNDING_BOX CENTROID AREA GEOHASH FROM_GEOHASH

### 14.3 — Evaluation, and why it is not just `eval`

- **Parser → AST → IR** (Phase 08). Formulas compile to the same IR as everything else, which
  means **a formula can be pushed down to SQL** when its functions have dialect lowerings.
  `=UPPER([name])` becomes `UPPER(name)` in Postgres rather than pulling the column.
- **Dependency graph and topological recalculation.** A formula column referencing another
  formula column recalculates in dependency order. Cycles are detected and reported with the
  offending path — reuse `service_workflows/graph.py`, which already does exactly this.
- **Vectorised, not row-by-row.** Every function is implemented over a whole column. A
  row-loop over 10M rows is a non-starter.
- **Null semantics stated explicitly.** SQL three-valued logic, not Excel's coercion, with the
  difference documented — because `"" = 0` being true in Excel is a source of real bugs.
- **Errors are values, not crashes.** `#DIV/0!`, `#VALUE!`, `#N/A`, `#REF!` propagate as a
  first-class error type. A bad row does not fail a 10M-row run; it produces an error cell,
  and the run reports how many.

### 14.4 — Authoring experience

Autocomplete on function names and column names, inline signature help, live preview of the
result on the first 20 rows *as you type*, an error squiggle with a plain-language message,
and a formula bar that expands for long expressions with syntax highlighting and bracket
matching.

### Done — delivered 2026-08-22

- [x] **87 functions**, not 250 — see below. Each has a declared signature, a result type,
      a pandas implementation and a null-propagation test
- [x] Excel's own precedence rules, pinned by test (`-3^2` is 9, `&` binds tighter than
      comparison, `=` is equality)
- [x] Formulas compile to IR; a supported formula pushes down and an unsupported one is
      reported as local with the reason
- [x] Evaluation is vectorised — every function runs over a whole column
- [x] A bad row becomes null and is counted, rather than failing the run
- [x] Errors are actionable: an unbracketed column suggests the brackets, a misspelled
      function suggests the nearest, a wrong column name suggests the right one

**87, not 250.** The roadmap's number counted a category list rather than an implementation
plan. What is here covers maths, text, temporal, logical, type and information; what is not
is financial (PV/IRR/XNPV), statistical (LINEST/percentile family), lookup (VLOOKUP/INDEX,
which need a second table and are really join steps), and window functions. Those are real
gaps, not a rounding error, and the honest count is the one above.

**Deliberately no SQL lowering** for `to_text` and `to_number`: `CAST(1.0 AS TEXT)` is "1.0"
in Postgres where the local path renders "1", and a failed cast raises in SQL where the local
path yields null. Pushing them would make the answer depend on where the query ran.

**Not done:** cell references (`A1`/`$A$1`) for pasted Excel formulas, autocomplete and
signature help in the editor (the Studio offers clickable column chips instead), and a
cross-column dependency graph — a formula cannot yet reference another formula column in the
same step, so there is no cycle to detect.

**Two bugs the phase surfaced:**
1. **Arithmetic typing reused `widen`**, which correctly refuses decimal-and-float because
   there is no *exact* common type — so `[amount] * [qty]` typed as `unknown` whenever the
   columns differed that way. Arithmetic and widening are different questions.
2. **`regex_extract` returned a DataFrame** when the pattern had more than one capture
   group: `expand=False` silently changes shape, and everything downstream broke.

---

## Phase 15 — Write-back: editing a source, safely ✅ COMPLETE (2026-08-22)

**The ask, verbatim:** *"if the dataset is sql the users can also directly add columns and rows
just like excel — for that the application can directly add query to make changes to sql."*

This is the most dangerous feature in the roadmap and the most valuable. It is also where a
careless implementation destroys a customer's production table. The entire design is therefore
built around **making the destructive case impossible to reach by accident**.

### 15.1 — The staging model

Edits never go straight to the source. They accumulate in a **change set**:

```python
GridEdit =
  | SetCell(row_identity, column, old_value, new_value)
  | InsertRow(values)
  | DeleteRow(row_identity, snapshot)      # snapshot enables undo
  | AddColumn(name, type, default)
  | DropColumn(name)
  | RenameColumn(old, new)
  | RetypeColumn(name, from_type, to_type)
  | SetPrimaryKey(columns)
  | AddIndex(columns) | AddConstraint(spec)
```

A change set is reviewable, diffable, discardable, shareable, and — for a governed project —
**approvable** through the Phase 03 approvals machinery already built. Nothing reaches the
database until an explicit **Commit** on a screen that shows exactly what will run.

### 15.2 — Row identity: the crux of the whole feature

An `UPDATE` whose `WHERE` clause does not identify exactly one row is a data-loss bug waiting
for its moment. So, in strict order of preference:

1. **Declared primary key** — use it.
2. **A unique constraint** — use it.
3. **A user-designated key** — validated for uniqueness against the live table *at commit
   time*, not at read time.
4. **A physical row identifier** — Postgres `ctid`, Oracle `ROWID`, SQLite `rowid`, SQL Server
   `%%physloc%%`. Usable, but **fragile across vacuums and rewrites**, so it is offered with
   that stated plainly and only within a short-lived session.
5. **Nothing available** → **editing is refused**, with an explanation and the offer to add a
   primary key (itself a DDL change requiring the same review).

There is no sixth option. "Match on all columns" is not offered, because it silently updates
every duplicate row.

### 15.3 — Concurrency

At read time each row carries a version token: a `xmin`/`rowversion`/`updated_at` where one
exists, otherwise a hash of the row's values.

```sql
UPDATE orders SET amount = 150.00
WHERE order_id = 4471 AND md5(...) = 'e3b0c442…';
```

Zero rows affected means somebody else changed it. The commit **stops**, shows a
three-way diff (original / theirs / yours) per conflicting row, and the user resolves. It does
not silently overwrite, and it does not silently skip.

### 15.4 — Generating the statements

The change set compiles through Phase 12's dialect layer:

- **Batched** — 5,000 single-row updates become a `CASE`-based bulk update, a temp-table join,
  or the dialect's `MERGE`, whichever that dialect supports.
- **Ordered** — DDL before DML; adding a column before writing values into it.
- **Transactional** — one transaction, with savepoints per logical group. Dialects without
  transactional DDL (MySQL) are flagged, because a partial failure there is not recoverable
  by rollback and the user deserves to know before pressing the button.

### 15.5 — The commit screen

Nothing about this step is implicit:

```
Commit 3 changes to postgres://prod/analytics.orders

  ⚠ This is a PRODUCTION environment.

  1. ALTER TABLE orders ADD COLUMN margin_pct numeric(10,4);
     → adds a column · no rows modified

  2. UPDATE orders SET amount = ... FROM (VALUES ...) AS v(...)
     WHERE orders.order_id = v.order_id;
     → 2,519 rows affected  ✓ dry-run confirmed

  3. DELETE FROM orders WHERE order_id IN (...);
     → 14 rows deleted  ⚠ not reversible

  [ Copy SQL ]  [ Download as migration ]  [ Dry run again ]  [ Commit ]
```

- **Dry run is real** — the statements execute inside a transaction that is then rolled back,
  and the reported row counts are the actual `rowcount` values, not estimates.
- **Blast-radius guard** — any statement affecting more than a configurable threshold (default
  1,000 rows, or >10% of the table) requires typing the table name to confirm.
- **Environment awareness** — production sources are visually distinct and can be set to
  require approval, reusing Phase 03's approval flow rather than inventing a second one.
- **Export instead of execute** — "Download as migration" produces a reviewed `.sql` file for
  teams whose process does not allow a tool to write to production. Refusing to support that
  workflow would just push people back to exporting to Excel.

### 15.6 — Non-SQL sources

| Source | Write-back behaviour |
|---|---|
| **Files (CSV/Excel/Parquet)** | Rewrite the file; previous version retained (Phase 18). Atomic write-then-rename, never in-place truncation |
| **Object storage** | Same, plus object versioning where the store supports it |
| **REST/SaaS** | Only where the manifest declares a writable endpoint with a row identifier. `PATCH` per row, batched where the API allows. Rate-limited and resumable |
| **NoSQL** | Document replace or field patch by `_id` |
| **Warehouses** | `MERGE` where supported; otherwise staged temp table + swap |
| **Streams** | **Refused.** You cannot edit a row in a log — offered as a compacted-topic write instead, or not at all |

### 15.7 — Everything is audited

Every committed change set writes to the Phase 03 audit log: who, when, which source, the
statements, row counts, and the change set id. A row's edit history is queryable. This is
non-negotiable — direct production writes without an audit trail would be the single worst
thing this platform could ship.

### Done when

- [x] No edit is possible without an established row identity; refusal is tested
- [x] Concurrent-modification conflicts are detected and surfaced, never silently resolved
- [x] Dry run reports real row counts from a rolled-back transaction
- [x] Blast-radius guard blocks a large unconfirmed change
- [x] Statements are generated for PostgreSQL, MySQL and SQLite — **run** against SQLite
- [ ] File write-back is atomic and previous versions are recoverable — **not built** (see below)
- [x] Every commit appears in the audit log with its statements
- [x] A destructive-scenario test suite (wrong key, stale read, partial failure, DDL rollback)

**Effort: large.** 3 sessions. The test suite is bigger than the implementation, correctly.

### What shipped

`services/service-writeback`, 11 API routes, migration `0027_writeback_change_sets`,
and a **Table editor** page at `/projects/{id}/table-editor`.

**Row identity** (`identity.py`) resolves in the documented order and refuses at step five.
A designated key is verified against live data before it is accepted, and a physical key
(`ctid`/`rowid`) is offered only with its caveat attached and never as a default.

**Six edit kinds**: `set_cell`, `insert_row`, `delete_row`, `add_column`, `drop_column`,
`rename_column`. `retype_column`, `set_primary_key`, `add_index` and `add_constraint` from
the sketch above are **not built** — each is a table rewrite on at least one target dialect,
which is a different risk profile and deserves its own design.

**Concurrency** is per cell, not per row, and compares values rather than hashes. A hash
function matching Python's is not portable across dialects, and getting it subtly wrong
would disable the check without failing anything. A concurrent change to a *different*
column of the same row is deliberately not a conflict — that is last-write-wins per cell,
which is how a grid behaves.

**Batching**: rows that set the same columns and check the same columns produce identical
SQL and run as one statement with many parameter sets. Five hundred pasted rows are one
round trip. The `WHERE` clause stays per-row, so the concurrency check keeps its precision;
only the row count is reported per batch, and a mismatch there stops the whole commit.
The `CASE`-based bulk update in the sketch was rejected: it cannot express a per-row
concurrency guard.

**A rehearsal leaves nothing behind.** This took two goes. SQLite has transactional DDL but
pysqlite only opens an implicit transaction for DML, so an `ALTER TABLE` in a dry run
committed itself and survived the rollback — the rehearsal *was* the change, and the real
commit then failed with "duplicate column name". SQLite now sits alongside MySQL in
`NON_TRANSACTIONAL_DDL`, its structure changes are skipped in the rehearsal and said to be
skipped, and a guard test asserts the schema is untouched after a dry run.

**Validation is change-set-wide.** Checking each edit against the table as it is today makes
the commonest gesture in the Studio impossible — add a column, then type values into it,
because the column does not exist yet. `validate_all` checks structure changes against the
table as it accumulates and row edits against the table as it will be once they have run.

**No-op edits are dropped at compile time.** Writing the value a cell already holds is not a
change, and it is also a dialect trap: MySQL reports rows *changed*, not rows matched, so
such an `UPDATE` returns zero and the concurrency check would read that as a concurrent edit.

**The blast-radius share rule has a floor.** One row of a three-row lookup table is 33% of it
and still one row; demanding the table name for that teaches people to type it without
reading. The share rule now ignores changes under 25 rows; the absolute limit still applies.

**Governed projects**: `POST .../commit` is the reviewable moment, and only that. Staging a
change set is the proposal, so gating the whole surface would make it impossible to prepare
a change for review. The refusal says "ask an approver to review and commit it", not the
generic "propose the edit as a change request", which would be wrong advice for a change set
that has already been proposed.

### Deliberately not done

- **File, object-storage, REST, NoSQL and warehouse write-back** (15.6). For a file-backed
  dataset the Studio's recipe model already covers this and covers it better: an edit becomes
  a replayable step rather than a destructive rewrite. Write-back exists because a live SQL
  table is somebody else's system of record and cannot be replayed onto. The table editor
  says so when a project has no database connection, rather than silently offering nothing.
- **Three-way conflict resolution UI.** A conflict stops the commit and reports which
  statement disagreed. Choosing between "theirs" and "yours" per row is a screen of its own.
- **Savepoints per logical group.** One transaction, all or nothing.
- **PostgreSQL and MySQL are written but unrun here.** No server on this machine. The SQL is
  dialect-aware through SQLAlchemy's preparer and the `NON_TRANSACTIONAL_DDL` set; that is
  not the same as having run it.

---

## Phase 16 — The transformation tool library: 20 → 400+ ⚠ PARTIAL (2026-08-23)

Today there are **20** step types. This is the full inventory of what a Studio needs to be the
only tool an analyst opens. Every entry compiles to Phase 08's IR, which means every entry gets
lineage, pushdown, and diffing without additional work.

Each tool is reachable three ways: the command palette (Ctrl+K), a right-click on the relevant
column or selection, and a categorised tool panel. **Context-sensitivity matters more than
count** — right-clicking a date column offers date tools first, not an alphabetical list of 400.

### Column structure (22)
add · duplicate · drop · drop-many · keep-only · rename · bulk-rename (pattern/regex) ·
reorder · move-to-start · move-to-end · sort-columns-alphabetically · retype ·
split-by-delimiter · split-by-position · split-by-regex · split-to-rows · merge-columns ·
concatenate-with-separator · derive (formula) · rename-from-first-row · promote-headers ·
demote-headers

### Row operations (20)
filter (visual builder) · filter (formula) · filter-by-selection · exclude-by-selection ·
keep-top-n · keep-bottom-n · keep-range · skip-first-n · skip-last-n · sort (multi-key) ·
custom-sort-order · reverse · shuffle · insert-row · delete-row · delete-blank-rows ·
delete-duplicate-rows · keep-errors · remove-errors · transpose

### Text (34)
trim · trim-leading · trim-trailing · collapse-whitespace · uppercase · lowercase ·
title-case · sentence-case · capitalise-each-word · pad-left · pad-right · truncate ·
substring · find · replace · replace-regex · extract-regex · extract-between · extract-before ·
extract-after · extract-first-n · extract-last-n · remove-characters · keep-characters ·
remove-accents · transliterate · slugify · reverse-text · repeat · count-occurrences ·
split-camel-case · normalise-unicode · detect-language · strip-html

### Numeric (30)
round · round-up · round-down · round-to-multiple · truncate · absolute · negate · reciprocal ·
power · square-root · logarithm · exponential · modulo · integer-divide · clamp · rescale ·
normalise-0-1 · standardise-z-score · robust-scale · bin-equal-width · bin-equal-frequency ·
bin-custom · quantile-bucket · percent-of-total · percent-change · cumulative-sum ·
running-average · difference · ratio · currency-convert · unit-convert

### Date & time (32)
parse-date · format-date · extract-year · extract-quarter · extract-month · extract-week ·
extract-day · extract-day-of-week · extract-day-of-year · extract-hour · extract-minute ·
truncate-to-period · add-interval · subtract-interval · difference-between ·
age-from-date · start-of-period · end-of-period · to-timezone · from-timezone ·
to-utc · epoch-to-date · date-to-epoch · business-days-between · add-business-days ·
is-weekend · is-holiday (calendar-aware) · fiscal-year · fiscal-quarter · fiscal-period ·
generate-date-spine · fill-missing-dates

### Type & conversion (16)
cast · to-text · to-number · to-integer · to-decimal · to-boolean · to-date · to-timestamp ·
to-json · parse-json · to-array · detect-type · coerce-with-fallback · locale-aware-number-parse ·
strip-currency-symbols · strip-thousands-separators

### Nulls & missing data (14)
fill-null-constant · fill-forward · fill-backward · fill-interpolate-linear ·
fill-interpolate-spline · fill-with-mean · fill-with-median · fill-with-mode ·
fill-from-another-column · replace-empty-string-with-null · replace-null-with-empty ·
drop-rows-with-nulls · drop-columns-mostly-null · flag-nulls

### Deduplication & matching (14)
remove-duplicates · remove-duplicates-by-columns · keep-first · keep-last · keep-most-complete ·
mark-duplicates · count-duplicates · fuzzy-dedupe (edit distance) · fuzzy-dedupe (phonetic) ·
fuzzy-dedupe (token) · cluster-similar-values · merge-cluster-to-canonical ·
survivorship-rules · golden-record

### Reshape (18)
pivot · unpivot · pivot-wider · pivot-longer · transpose · group-to-array · explode-array ·
explode-json · flatten-nested · nest-columns · split-into-tables · cross-tab · stack ·
unstack · wide-to-long · long-to-wide · fill-down-merged-cells · normalise-to-relational

### Join & combine (16)
inner-join · left-join · right-join · full-outer-join · cross-join · semi-join · anti-join ·
fuzzy-join (similarity threshold) · as-of-join (temporal) · range-join · union · union-all ·
intersect · except · append-datasets · merge-by-position

### Aggregation & grouping (26)
group-by · sum · average · median · mode · min · max · count · count-distinct · count-null ·
first · last · nth · list-collect · string-agg · standard-deviation · variance · percentile ·
quartile · range · product · any-true · all-true · correlation · covariance · weighted-average

### Window & analytic (22)
row-number · rank · dense-rank · percent-rank · ntile · lag · lead · first-value · last-value ·
nth-value · cumulative-sum · cumulative-product · cumulative-max · cumulative-min ·
moving-average · moving-sum · moving-max · moving-min · exponential-moving-average ·
rolling-stdev · rolling-correlation · session-window

### Statistical (28)
describe · correlation-matrix · covariance-matrix · histogram · frequency-table ·
cross-tabulation · outlier-detection-iqr · outlier-detection-zscore · outlier-detection-mad ·
outlier-detection-isolation-forest · normality-test · t-test · paired-t-test · anova ·
chi-square · mann-whitney · kolmogorov-smirnov · linear-regression · multiple-regression ·
logistic-regression · residual-analysis · confidence-interval · sample-size-calculator ·
seasonal-decompose · autocorrelation · trend-test · changepoint-detection · distribution-fit

### Cleansing & standardisation (24)
standardise-case · standardise-whitespace · standardise-phone (E.164) · standardise-email ·
validate-email · standardise-address · parse-address-components · standardise-country ·
standardise-currency-code · standardise-name · split-full-name · standardise-postal-code ·
standardise-url · normalise-boolean-tokens · normalise-null-tokens · fix-encoding-mojibake ·
remove-control-characters · standardise-line-endings · detect-and-fix-swapped-columns ·
trim-quotes · unescape · standardise-units · standardise-date-format · lookup-standardise

### Validation & assertions (18)
assert-not-null · assert-unique · assert-in-set · assert-range · assert-regex ·
assert-type · assert-referential-integrity · assert-row-count · assert-no-duplicates ·
assert-monotonic · assert-sum-equals · assert-freshness · assert-schema-matches ·
assert-distribution-stable · quarantine-failures · flag-failures · fail-run-on-violation ·
custom-assertion (formula)

### Enrichment & lookup (16)
lookup-from-dataset · lookup-from-file · lookup-with-default · reverse-lookup ·
lookup-multiple-columns · fuzzy-lookup · hierarchy-lookup · date-dimension-join ·
currency-rate-join (historical) · timezone-from-coordinates · country-from-ip ·
domain-from-email · company-from-domain · calendar-join · geocode · reverse-geocode

### Geospatial (14)
parse-coordinates · distance-between · haversine · bearing · within-radius ·
point-in-polygon · nearest-neighbour · bounding-box · centroid · area · buffer ·
geohash-encode · geohash-decode · to-geojson

### Sampling & splitting (12)
random-sample · stratified-sample · systematic-sample · cluster-sample · top-n-per-group ·
train-test-split · time-based-split · split-by-value · split-by-condition · split-into-n-parts ·
reservoir-sample · balanced-sample

### Applied statistics & ML (18)
k-means-cluster · hierarchical-cluster · dbscan · pca · anomaly-score · forecast-arima ·
forecast-exponential-smoothing · forecast-prophet-style · impute-knn · impute-iterative ·
classify-naive-bayes · classify-decision-tree · feature-importance · one-hot-encode ·
ordinal-encode · target-encode · text-vectorise-tfidf · similarity-matrix

> Each of these reports its **method** and its **confidence**, following the Phase 06 rule that
> a result which cannot explain itself should not be shown. None of them call a language model.

### Encoding, hashing & privacy (16)
md5 · sha1 · sha256 · sha512 · hmac · base64-encode · base64-decode · url-encode · url-decode ·
html-escape · mask-partial · mask-full · tokenise-reversible · pseudonymise-consistent ·
generate-surrogate-key · generate-uuid

### Code & escape hatches (10)
sql-step (arbitrary SELECT against the source) · python-step (sandboxed, resource-limited) ·
formula-column · regex-workbench · jq-style JSON step · lookup-table-inline · http-enrich-step ·
shell-free file transform · template-render · custom-plugin (Phase 23)

### Metadata & documentation (12)
set-column-description · set-column-tags · set-dataset-owner · link-to-glossary-term ·
mark-column-pii · set-column-classification · add-step-note · generate-data-dictionary ·
snapshot-schema · compare-schema-to-snapshot · export-recipe-as-yaml · import-recipe-from-yaml

### Productivity & recipe management (14)
undo · redo · duplicate-step · disable-step · reorder-step · group-steps-into-macro ·
save-as-template · apply-template · parameterise-step · branch-recipe · merge-branch ·
compare-recipes · comment-on-step · replay-recipe-on-new-file

**Total ≈ 420 tools.**

### Done when

- [x] Every tool compiles to IR (or declares itself `Extension` and never pushes down)
- [x] Every tool has unit tests including empty input, all-null input, and single-row input
- [x] Every tool declares which types it accepts; the UI never offers a date tool on a number
- [x] Context menus are type-aware
- [x] Command palette fuzzy-searches every tool by name and synonym
- [x] Every tool appears in generated documentation with an example

**Effort: very large, but the most parallelisable work in the roadmap.** Tools are independent;
they can be delivered in category batches, each shippable on its own.

### What shipped: 167 tools, and the machinery for the rest

**167, not 420.** The count above was a wish list; this is what exists, is tested,
and is documented. The categories delivered are the ones an analyst opens a file
to fix — text (43), dates (33), numeric (23), cleansing (15), encoding and
privacy (14), conversion (10), validation (9), columns (7), rows (7), missing
data (6). What is absent is listed at the end of this section, by name.

**The architecture is the deliverable.** A library of hundreds cannot be a
hundred modules held to a standard by whoever remembers it, so a tool is
declared as data — a `ToolSpec` carrying its name, category, synonyms, accepted
types, parameter schema, a `build` function returning IR, and a worked example.
Four things fall out of that shape, and each replaces a convention with a
mechanism:

- **Every tool compiles to IR**, so type inference, column lineage and pushdown
  come free. `test_tool_pushdown.py` proves it rather than asserting it: every
  tool run through the IR equals the same tool run through the step engine, and
  the pushable ones produce real Postgres SQL.
- **Every tool is tested identically.** `test_tool_library.py` iterates the
  registry and runs *all* of them against empty, all-null and single-row input.
  A new tool cannot arrive without those cases, because nobody has to remember.
- **Every tool declares its types**, so the context menu and the catalogue API
  filter from one declaration rather than a list maintained in the front end.
- **Every tool documents itself and the documentation is executed.**
  `docs/transformation-tools.md` is generated by
  `scripts/generate-tool-reference.py`, every example in it is asserted by a
  test, and a further test fails if the checked-in file drifts from the registry.

**One `tool` step type covers all of them.** Adding a tool must not mean editing
the step vocabulary, the validator, the lineage table and the UI catalogue in
four places — which is precisely how a library of hundreds stops being
consistent. Lineage for a tool is derived from the tool's own IR node, so there
is no second description of what a tool does to a column list.

**The IR function catalogue grew 87 → 186.** Most of the new ones declare no SQL
lowering, and that is the Phase 08 rule holding rather than breaking: a function
whose SQL means something *close to* the local implementation is worse than one
that stays local, because the difference only shows up as numbers that disagree
depending on where the pipeline ran. 77 functions lower to Postgres.

**Three real bugs the new tests found in old code:**

- `abs()` and `round()` raised on an all-null column, because a numeric column
  that happens to be entirely null arrives as object dtype — the normal state of
  an optional column in a sparse file.
- `to_date` had no `errors="coerce"`, so one unparseable value failed the whole
  run instead of nulling one row. Its siblings had it but no `format="mixed"`,
  which meant a column mixing `2026-01-01` and `1 Jan 2026` silently lost half
  its rows to a format inferred from row one.
- `starts_with`, `ends_with` and `contains` had no lowering at all. They now
  lower through `POSITION`, not `LIKE`: `x LIKE y || '%'` turns a `%` in the
  needle into a wildcard, so `starts_with(sku, "10%")` would have matched
  "10ABC" in SQL and not locally.

### Deliberately not built

Named rather than implied. Each is a genuine piece of work, not a gap in the
mechanism — every one of them would be declared exactly the way the 167 are.

- **Window and analytic functions** (row_number, rank, lag, moving averages).
  The IR has no window node; adding one is a change to the algebra, not a batch
  of tools, and it belongs with Phase 22's optimiser work.
- **Statistical and ML tools** (regression, clustering, forecasting, PCA). These
  are not row-wise expressions and cannot push down; they need a different node
  type and a story about where the model lives.
- **Geospatial**. Needs a geometry type in the lattice.
- **Fuzzy joining, clustering and survivorship.** Phase 06 already does entity
  resolution properly; wrapping it as tools without connecting the two would
  give two answers to one question.
- **Enrichment tools that call out** (geocode, IP lookup, company from domain).
  They need credentials and a network policy, and a tool that silently makes an
  HTTP request per row is a surprise nobody wants.
- **Reshape beyond what exists.** `pivot`, `unpivot` and `split_column` are
  already `Extension` nodes from Phase 08; the rest of that category is the same
  shape of work.
- **Recipe management** (undo, macros, templates, branching). That is a Studio
  feature rather than a transformation, and it belongs with Phase 21.

---

## Phase 17 — SQL IDE, notebook, and the escape hatch ✅ COMPLETE (2026-08-23)

No visual tool covers everything, and pretending otherwise is what makes people abandon
low-code platforms. The escape hatch has to be first-class, not an afterthought.

### 17.1 — SQL workbench
Schema tree browser · autocomplete from live schema · syntax highlighting per dialect ·
multi-statement execution with per-statement results · `EXPLAIN` visualisation · query
history with timing · saved queries · parameterised queries · **read-only by default** with
writes requiring the same guard rails as Phase 15 · result grid is the *same* Phase 13 grid,
so a query result can be transformed further, charted, or exported without leaving.

### 17.2 — Notebook
Interleaved SQL, Python, and visual-recipe cells sharing one namespace; a recipe cell's output
is a dataframe the next Python cell can read, and a Python cell's output is a dataset the next
visual cell can transform. Cells are versioned with the notebook; execution is out-of-process
on the Phase 01 worker, so a long-running cell does not hold an HTTP connection.

### 17.3 — Python sandbox
Restricted imports (an allowlist, extending the `expressions.py` posture), CPU and memory
limits, no network by default, a wall-clock timeout, and no filesystem access outside a scratch
directory. A `python-step` that cannot be sandboxed properly on a given deployment is
**disabled with a stated reason** rather than run unsafely.

### 17.4 — Recipe as code
Every recipe serialises to readable YAML and round-trips losslessly. Edit the YAML, the visual
recipe updates; edit visually, the YAML updates. Recipes live in git alongside application
code, get reviewed in pull requests, and diff meaningfully. This is what lets a data team adopt
the tool without abandoning their engineering practice.

### Done when
- [x] SQL workbench round-trips results into the grid
- [x] Notebook cells share state across languages
- [x] Sandbox escape attempts are covered by tests; unsandboxable deployments disable the step
- [x] YAML round-trip is lossless for every recipe in the test corpus

**Effort: medium-large.** 2–3 sessions.

### What shipped

`services/service-workbench`, 19 API routes, migration `0028`, and three pages:
**SQL workbench** at `/projects/{id}/workbench`, **Notebooks** at
`/projects/{id}/notebooks`, and a **recipe-as-code** panel inside the Studio.

**The workbench splits scripts rather than refusing them.** Extraction accepts
one read-only SELECT, which is right for extraction and impossible for a
workbench: people paste scripts. `sql_text.py` scans the original characters --
not a stripped copy -- so statements come back with their formatting, comments
and character offsets intact, and "error in statement 3" can point at statement
3. It survives semicolons inside literals, doubled and backslash-escaped quotes,
quoted identifiers, comments, and PostgreSQL dollar-quoted function bodies.

**Read-only is a default, not a suggestion.** Every request asks for its mode,
the service narrows it to what the role carries, and the response says which
policy was actually in force -- a client cannot believe it is read-only when it
is not. Writes need **admin**, because writing to a source database by hand
bypasses every review the rest of the platform applies. Classification catches
the cases a leading-keyword check misses: a data-modifying CTE (`WITH x AS
(DELETE ... RETURNING *)`) is a write, and `EXPLAIN ANALYZE INSERT` is a write
because it executes the insert.

**Statement timeouts are set per dialect** (`statement_timeout` for PostgreSQL,
`max_execution_time` for MySQL), and a dialect with none says so rather than
staying quiet. Without this a workbench is a way to take a database down: a
runaway query holds a server-side connection long after the browser tab closes.

**Autocomplete narrows by cursor position** -- tables after `FROM`, that table's
columns after `alias.`, the joined tables' columns after `SELECT` -- and reads
the *whole* statement, not just the text before the cursor, because people write
`SELECT <cursor> FROM orders` by going back.

### The sandbox, and what it actually guarantees

`sandbox.py` runs Python in a spawned process with an import allowlist, a
CPython **audit hook**, `RLIMIT_CPU`/`RLIMIT_FSIZE`/`RLIMIT_NOFILE`, and a
wall-clock deadline enforced by the parent.

Two escapes got through earlier versions and are now regression tests:

1. `object.__subclasses__()` reaches `BuiltinImporter`, and `load_module("os")`
   returns the **cached** module without performing an import -- so no `import`
   event fires and an allowlist on `__import__` is irrelevant. Fixed by purging
   the dangerous modules from `sys.modules` before the cell starts, which turns
   every such route back into a real import the hook refuses.
2. `os._wrap_close.__init__.__globals__["system"]` is reachable regardless,
   because purging the lookup table does not unload the class. The audit hook is
   what stops it, firing on `os.system` wherever the call came from.

**Capabilities are probed, not assumed, and this machine fails the probe.**
`hasattr(resource, "RLIMIT_AS")` is true on macOS and `setrlimit` raises --
so an earlier version claimed a memory limit it did not have. The probe now
spawns a child and tries. On Darwin the answer is no, so **Python cells are
disabled here with a stated reason**, which is exactly the behaviour 17.3 asks
for. `run()` is the mechanism and `require_usable()` is the policy, kept apart
so the escape tests still exercise the barriers on a platform the policy
declines.

### Deliberately different from the sketch

- **Notebooks run in the request, not on the Phase 01 worker.** The stated
  reason for the worker was that a long cell must not hold an HTTP connection.
  What is here instead is a bound on how long a cell *can* be: 15s per Python
  cell, a statement timeout on SQL, and `MAX_RUN_SECONDS = 120` for the whole
  notebook. A run that cannot exceed two minutes does not need a queue to keep
  it off the request, and a queue would add a job table, a worker node type and
  polling to every client for the same result. Moving it becomes worth doing
  when notebooks are allowed to run long — a decision about limits, not plumbing.
- **Only DataFrames cross between cells.** A Python cell's scalars and objects
  stay in that cell: a SQL cell cannot read a Python class and a recipe cell
  cannot transform one, so letting them into the namespace would make "shared"
  mean "shared with one of the three".
- **The editor is a `<textarea>`, not a library.** Its genuinely hard parts --
  which statement the cursor is in, ranking completions, what "run" means with a
  selection -- are logic in `editor-state.ts` and unit tested, the same reasoning
  that keeps this repository free of chart and icon libraries.

---

# TRACK D — Platform depth

These are the capabilities that separate a good tool from infrastructure a company builds on.
They are sequenced last because each depends on the foundations, not because they matter less.

---

## Phase 18 — Time travel & dataset versioning

**The idea:** every dataset is an append-only sequence of immutable snapshots, addressable by
time. Not a feature — a substrate that several others sit on.

- `SELECT ... AS OF '2026-03-01'` on any dataset.
- **Diff any two versions**: rows added, removed, changed, per-cell. The Phase 03 version
  history did this for *definitions*; this does it for *data*.
- **Rollback** a bad load without re-running the pipeline.
- **Reproducibility**: a run pins the exact source versions it read, so re-running a report
  from six months ago produces the number it produced then, not today's number. This is the
  single most requested thing in regulated industries and almost nothing offers it.
- Storage: copy-on-write with content-addressed chunks; Parquet + a manifest, essentially an
  Iceberg-lite. Retention policies (Phase 07) decide how far back versions are kept.

**Unlocks:** audit-grade reproducibility, safe rollback, meaningful data diffs, and the
"compare environments" feature below.

---

## Phase 19 — Semantic layer & data contracts

**The problem it solves:** every company has four definitions of "active customer" and they
disagree by 8%. The argument is never resolved because the definitions live inside four
different dashboards.

### Semantic layer
Define **metrics** and **dimensions** once, centrally, with an owner and a description:

```yaml
metric: active_customers
  description: Customers with ≥1 order in the trailing 90 days
  owner: revenue-analytics
  expression: COUNT(DISTINCT customer_id)
  filters: [order_date >= today() - 90]
  dimensions: [region, plan_tier, acquisition_channel]
  valid_from: 2026-01-01
```

Every chart, report, pivot and export resolves through it. Changing the definition changes it
everywhere at once, with a version history and an impact analysis (Phase 02) showing what will
move before it moves.

### Data contracts
A producer publishes a contract — schema, types, nullability, freshness SLA, allowed value
ranges, expected volume. Consumers subscribe. A change that breaks the contract is **blocked
at the pipeline**, not discovered by a consumer three weeks later. This is Phase 02's drift
detection turned from a warning into an agreement with two sides.

---

## Phase 20 — Streaming & change data capture

Batch is not enough for "the dashboard should be current". Two additions:

**CDC** — read the database's own change log rather than polling: Postgres logical replication,
MySQL binlog, MongoDB change streams, SQL Server CDC. Initial snapshot, then a continuous
stream of inserts/updates/deletes, with resumable position tracking.

**Streaming transforms** — the tool set changes shape here, which is the point:
tumbling / hopping / sliding / session windows · watermarks and late-arrival handling ·
stateful aggregation with checkpointing · stream-table joins · exactly-once semantics where
the sink supports it, **at-least-once with the duplicate risk stated where it does not**.

Sources: Kafka, Kinesis, Pub/Sub, Event Hubs, Pulsar, RabbitMQ, NATS, MQTT, and inbound
webhooks. Micro-batch first (seconds of latency, far simpler to reason about), with true
continuous execution behind it only where the latency requirement justifies the complexity.

---

## Phase 21 — Real-time collaboration

Two analysts in the same Studio, seeing each other's cursors, without overwriting each other.

CRDT-based recipe editing (the step list is a sequence CRDT; step configs are last-writer-wins
per field) · presence and live cursors · cell-level comment threads that resolve · @mentions
into the Phase 03 notification system · a change feed per dataset · suggestion mode, where a
viewer proposes steps an editor accepts or rejects — the review workflow that makes it safe to
give a wider audience access.

---

## Phase 22 — Cost-based optimizer & performance

Phase 12 decides *where* to run. This decides *how well*.

- **Statistics**: row counts, distinct counts, histograms, null fractions per column, refreshed
  on a schedule, used to estimate selectivity.
- **Rewrites**: predicate pushdown and pull-up, projection pruning, join reordering, constant
  folding, common-subexpression elimination, redundant-sort removal, limit pushdown.
- **Federated queries**: joining Postgres to Snowflake to a CSV in one query, with the
  optimizer deciding which side to move and whether to ship a filter as an `IN` list.
- **Caching**: content-addressed intermediate results, so an unchanged prefix of a recipe is
  never recomputed. Editing step 14 of 15 should be instant.
- **Incremental materialisation**: recompute only the partitions whose inputs changed.
- **Adaptive execution**: if a join's real cardinality diverges wildly from the estimate,
  switch strategy mid-run rather than finishing badly.
- **Resource governance**: per-project concurrency limits, priority queues, and a hard memory
  ceiling per run so one bad query cannot take the platform down.

---

## Phase 23 — Extensibility & ecosystem

The difference between a product and a platform.

**Plugin SDK** — custom connectors, custom transformation steps, custom formula functions,
custom chart types, all through published, versioned, capability-declared interfaces that pass
the same conformance suites as first-party code.

**Public API & CLI** — scoped API tokens, a full REST surface, an OpenAPI spec, and
`pipewright run <workflow>` so the platform fits into existing CI rather than replacing it.
Terraform provider for infrastructure-as-code teams.

**Migration importers** — read a **dbt** project, an **Airflow** DAG, an **Alteryx** workflow,
an **Informatica** mapping, an **SSIS** package, a **Talend** job, a **Power Query** M script,
and produce an editable Pipewright recipe. Reported honestly: what converted, what did not, and
why. Nothing removes adoption friction like not having to rebuild two years of work by hand.

**Marketplace** — community connectors, recipe templates by industry, and shared metric
definitions, each carrying its verification tier.

**Embedded mode** — the Studio as an embeddable component, white-labelled, so SaaS companies
can offer their own customers data preparation without building it. A large business on its own.

---

# Beyond the roadmap: bets worth taking

Ideas that are not scheduled because they are speculative, but which are worth prototyping
because any one of them could be the thing that defines the category.

### Local-first execution in the browser
Ship DuckDB-WASM to the client and run preview transformations **entirely in the browser** on
a sampled slice. Every keystroke in the formula bar, every filter, every step reorder previews
in single-digit milliseconds with no server round-trip. Full runs still go server-side. The
felt difference between 12ms and 400ms feedback is the difference between a tool people tolerate
and one they enjoy — and nobody in this category has done it.

### What-if simulation over lineage
Phase 02 already computes downstream impact. Extend it from *structural* to *numerical*:
"if I change this filter, which reports move, and by how much?" — computed by executing the
affected subgraph against a sample and diffing the results. Change management for data.

### Auto-healing schema drift
When a source adds a column, drift is detected today. Go further: propose the recipe patch,
show its impact, and apply it on approval. Most drift is benign and handling it is toil.

### Compliance evidence, generated
GDPR Article 30 records, data-processing inventories, PII flow maps, retention proofs, access
reviews — all of it is derivable from lineage, classification, and the audit log that already
exist. Auditors ask for exactly this and companies build it by hand every year.

### Data mesh support
Domain-owned datasets with published contracts, a federated catalogue, and cross-domain
discovery — the organisational model large companies are moving to, with almost no tooling.

### Natural language over the semantic layer
Not "AI writes your pipeline", which fails because it hallucinates joins. Instead: natural
language constrained to a **defined semantic layer**, where the space of valid answers is
enumerable and every response shows the metric definition it resolved to. The honesty
constraint from Phase 06 makes this tractable where the general version is not.

### Continuous data testing
Treat data like code: a test suite that runs on every load, a coverage measure for how much of
the warehouse is under assertion, and a red/green history per dataset.

---

# Sequencing & effort

Effort is in **focused sessions** (a session ≈ one long working block ending with the full
verification gate green). This is a planning unit, not a promise.

| # | Phase | Track | Effort | Depends on | Ships value on its own? |
|---|---|---|---|---|---|
| 08 | Type system & IR | A | 4 | — | No (enabling) |
| 09 | Design system & themes | A | 2 | — | **Yes** — immediately visible |
| 10 | Connector factory (250 sources) | B | 6+ | 08 | **Yes** — per batch |
| 11 | Ingestion intelligence | B | 3 | 08 | **Yes** |
| 12 | Pushdown & dialects | B | 4 | 08 | **Yes** — unlocks scale |
| 13 | Data grid | C | 4 | 09 | **Yes** — the flagship |
| 14 | Formula engine | C | 3 | 08, 13 | **Yes** |
| 15 | Write-back | C | 3 | 12, 13 | **Yes** |
| 16 | Tool library (420) | C | 6+ | 08, 13 | **Yes** — per batch |
| 17 | SQL IDE & notebook | C | 3 | 12, 13 | **Yes** |
| 18 | Time travel | D | 3 | 08 | **Yes** |
| 19 | Semantic layer & contracts | D | 3 | 08, 18 | **Yes** |
| 20 | Streaming & CDC | D | 4 | 08, 10 | **Yes** |
| 21 | Collaboration | D | 3 | 13 | **Yes** |
| 22 | Optimizer | D | 4 | 12, 18 | Partly |
| 23 | Extensibility | D | 3 | most | **Yes** |

**≈ 58 sessions total.**

### Recommended order

**Start here — the shortest path to a product that feels transformed:**

```
09 (themes) → 08 (types & IR) → 13 (grid) → 14 (formulas) → 12 (pushdown) → 15 (write-back)
```

That sequence is ~20 sessions and delivers the entire thesis: a fast, professional, light-and-dark
spreadsheet over any source, with real calculations, that can push work down and write changes
back. Everything after it is breadth on a proven core.

**Why 09 first** despite 08 being more important: it is two sessions, it is independent, and
every UI phase that follows would otherwise be built against tokens that are about to change.

**Why not connectors first**, despite being ask #1: 250 connectors feeding a Studio that is
still a step list is 250 connectors nobody enjoys using. Connectors are also the most
parallelisable work in the roadmap — they can run as batches alongside anything else once the
factory (Phase 10, gated on 08) exists.

---

# Principles that carry forward

These governed Phases 01–07 and are not renegotiated by scale. They are why the completed work
holds up, and every phase above is written to obey them.

1. **Never lie about capability.** A declared capability is what works *here*, not what was
   designed. At 250 connectors this becomes verification tiers, visible at the point of choice.
2. **Fail closed.** An unrecognised write path requires `editor`. A security rule naming a
   missing column hides everything. A dialect that cannot express a node refuses rather than
   approximating.
3. **Decide once, in one place.** Permission, tenancy, aggregation, type mapping. Every
   duplicated decision is a future divergence.
4. **Validate before running, not after.** Chart shapes, cast losses, blast radius, formula
   types — the error is worth more before the run than during it.
5. **State the method.** Every inferred, suggested or estimated result says what produced it
   and how confident it is. No result appears that cannot explain itself.
6. **Derive, do not store, what can go stale.** Lineage is computed from the recipe. The same
   applies to schemas, profiles and impact.
7. **Tests prove behaviour, not coverage.** The differential test — predicted vs actual, SQL vs
   pandas — has found more real bugs in this project than every unit test combined.
8. **Destructive actions are explicit, previewed, reversible, and audited.** Especially in
   Phase 15, where the cost of getting it wrong is somebody's production table.

---

# The one decision to confirm before starting

**The Phase 09 palette.** The roadmap proposes graphite neutrals with a green-cyan bias, a deep
teal accent, and copper as the single warm note — chosen to move away from the cyan-to-indigo
gradient that currently makes the app look like every other AI-era dashboard, and to keep the
blue end of the spectrum free for data series.

That is a taste decision, it is cheap to change now and expensive later, and it is the only
thing in this document that genuinely needs sign-off before work starts. Everything else is a
judgement call the implementation can make.
