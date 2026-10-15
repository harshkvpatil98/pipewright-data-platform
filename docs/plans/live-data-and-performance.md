# Live data and performance

**Date:** 2026-10-15, after C1 and C2 (`contracts-and-collaboration.md`).
**Purpose:** finish the next two roadmap v2 phases that were left partial:
**Phase 20, streaming and change data capture** (production-readiness P9
shipped webhooks and a first PostgreSQL change reader) and **Phase 22, the
cost-based optimiser** (P9 shipped five rewrites). Phase 16's missing tool
families and Phase 23 stay where `docs/HANDOFF.md` §8 says they are.

**Status:** D1 (live data) done 2026-10-15; D2 (performance) next.

Each phase measures first, says what it will deliver and when it is done,
then records what shipped. The rules in `AGENTS.md` and the A0 vocabulary
apply: recipe, check, import, deliver, schema change; sentence case; no
em-dashes; UK spelling; `count_of`, never "(s)".

Everything here is proven on one machine and in CI against real servers or
the vendors' own test servers. A connector tested only against a vendor's
emulator is tier 2 ("Tested against a real server or a test server that
answers the way the vendor documents"), which is what that tier says.

---

## D1 — Live data (roadmap Phase 20) *(done 2026-10-15)*

**Why.** Batch is not enough for "the dashboard should be current". The
roadmap asks for change capture from four databases' own change logs, an
initial snapshot then a continuous stream with resumable positions,
streaming transforms (four kinds of window, watermarks, late arrivals,
checkpointed state, stream-table joins), exactly-once where the sink
supports it and at-least-once stated where it does not, and eight message
queues besides webhooks. Micro-batch first.

### D1 specification (written 2026-10-15)

**Measured before starting** (`scratchpad/p20/baseline_d1.py`, dev stack,
a scratch database on the logical PostgreSQL):

| | Now |
|---|---|
| A table with 1,000 rows, then a change-capture source on it | First poll stores 0 events: no initial snapshot, so the dataset never holds those rows |
| A change committed while a poll is running | **Lost.** The poll peeks, stores, then peeks again to find the position to consume up to; the second peek sees the new change, the slot is advanced past it, and it was never stored |
| One row inserted, updated, deleted | The dataset has 3 rows (the log). There is no "table as it is now" |
| 20,000 changes | 41 polls of 500; at one poll per 30-second tick, 20 minutes behind |
| Saving after one more event | Rewrites every event ever received (0.40 s for 20,004; grows without end) |
| A webhook sender retries with the same `Idempotency-Key` | Stored twice |
| Kinds | `webhook`, `postgres_cdc`. No MySQL, MongoDB, SQL Server, no queue |
| Windows, late data, state, lookups | None |
| CI | The change-capture test skips (the CI PostgreSQL runs `wal_level=replica`) |

**L1. Change capture that keeps a table current.** A change-capture source
follows tables. Its first pass reads every row (the snapshot), then follows
the change log from a position taken *before* the snapshot, so nothing that
changes during it is missed; changes applied twice converge, because a
change is applied by key. For each followed table the source keeps **"the
table as it is now"** as a dataset (inserts and updates replace the row with
that key, deletes remove it), as well as **every change** in the source's
log dataset. A table without a primary key is followed as a log only, and
says so. The PostgreSQL consume race is fixed: the position consumed up to
comes from the same read that was stored. Positions resume after a restart.

**L2. Four databases.** PostgreSQL (logical replication, `test_decoding`),
MySQL (the row-based binary log, `mysql-replication`), MongoDB (change
streams, `pymongo`, needs a replica set) and SQL Server (its CDC tables,
`pymssql`, needs CDC enabled on the database and the table). Each checks its
own requirements first and says what to change in the database's words
("binlog_format is MIXED; change capture needs ROW").

**L3. Eight queues.** Kafka, Azure Event Hubs (through its Kafka endpoint),
Amazon Kinesis, Google Pub/Sub, Apache Pulsar, RabbitMQ, NATS JetStream and
MQTT, plus the existing webhook. Each declares its settings (secrets
encrypted at rest), can be tested before it is saved, is read in
micro-batches, and states its delivery guarantee where it is chosen and on
the source's page:

- **Saved once, by position** (the position is saved in the same
  transaction as the events, and a restart reads from it): Kafka, Event
  Hubs, Kinesis, Pulsar (reader), NATS (stream sequence), and the MySQL,
  MongoDB and SQL Server change logs.
- **Saved once, by message id** (acknowledged after saving; a redelivery is
  recognised by its id): PostgreSQL (change position), Pub/Sub, RabbitMQ
  messages that carry an id, webhooks that send an `Idempotency-Key`.
- **At least once** (a redelivery after a crash can be saved twice): MQTT,
  RabbitMQ messages without an id, webhooks without a key.

A message's body becomes columns (JSON is flattened; anything else is
text), with its key, headers or attributes, and its broker time.

**L4. Live recipes: streaming transforms.** A live recipe runs on a live
source's events as they arrive:

- *Steps*: a saved recipe whose steps work row by row (filter, derive,
  rename, cast, clean, split and similar); one that needs every row
  (sort, deduplicate, aggregate, pivot) is refused with the step named,
  because a window does that job here.
- *Look up* (the stream-table join): match each event to a dataset's rows on
  one or more columns and bring chosen columns along; events without a
  match are kept with empty values or dropped. The dataset is read as it is
  when the batch runs, and a new version is picked up on the next batch.
- *Summarise by time*: tumbling (fixed, back to back), hopping (fixed,
  overlapping, every so often), sliding (the last so many minutes at every
  moment an event enters or leaves) and session (activity separated by a
  gap) windows, grouped by columns, with count, sum, average, lowest,
  highest, first and last.
- *Event time and lateness*: windows follow a column's time or the arrival
  time. The watermark is the latest time seen minus the allowed lateness;
  a window is final once the watermark passes its end. A late event is
  dropped and counted, or, when asked, updates a window closed within the
  last so many minutes, which is marked restated.
- *State and exactly-once*: open windows, the watermark and the last event
  processed are saved in the same transaction as the results, so a crash
  repeats a batch without counting anything twice. The output is a dataset
  with a new version at the source's save interval, open windows marked
  "still open"; inside Pipewright every event is counted exactly once
  (subject to the source's own guarantee above).
- *Sinks*: the output dataset delivers like any other. Delivering to
  PostgreSQL or MySQL by key (upsert on the window and group columns) is
  exactly-once; appending is at-least-once and the delivery form says so.

**L5. A runner that keeps up.** A dedicated `live_runner` process (in
`scripts/worker.sh`, the compose file and the Helm chart) reads each active
source every few seconds (default 5, at least 1), 5,000 events a batch,
until it has caught up, under a lease so several runners never read one
source together. A failing source backs off (to 5 minutes) and its owner
is told once after five failures in a row. Each source reports how far
behind it is, events per minute, and when it last saved. Events are kept
for 7 days once saved and processed; the log dataset keeps the rest. Saving
appends to the previous version instead of rewriting every event.

**L6. In the product.** A **Live** tab under Data lists live sources with
their state, how far behind they are and their last event; adding one picks
a kind (grouped, with tier badges), fills its settings, tests it and saves.
Each source has a page: guarantee, throughput over the last hour, tables
kept current, the log dataset, live recipes (with their open windows,
watermark and late counts), recent events, and pause, resume, save now and
delete. A live recipe is added from that page. Datasets kept by a live
source say so. Help (data page, glossary, API guide), audit words, error
messages, activity, the Python client and `docs/api/openapi.json`.

**L7. Proven against real servers.** Unit tests for every window kind against
a brute-force reference, lateness, restating, crash-and-repeat, the lookup
and every guarantee; a `live` CI job starts PostgreSQL (logical), MySQL,
MongoDB (replica set), SQL Server, Kafka, Kinesis's test server, Pub/Sub's
emulator, Pulsar, RabbitMQ, NATS and Mosquitto, and runs each kind's
round trip; `scripts/check-live-servers.py` fails the job rather than letting
a test skip quietly. The change-capture test no longer skips on CI.

**Done when.** The baseline's 1,000 rows are in the table's current dataset
after the first pass; the raced change is stored; insert, update and delete
leave the current dataset with the right rows; 20,000 changes are caught up
in under a minute; a retried webhook with a key is stored once; every kind
round-trips against its server in CI; a live recipe's tumbling, hopping,
sliding and session windows match the reference, survive a crash mid-batch
without double counting and handle late events both ways; the Live tab,
source page and live recipe form work at 1280 and 1024; `npm run verify` is
green with no `.env`; CI green.

### What shipped

- **L1, tables kept current.** A change-capture feed takes its position in
  the change log, then reads each followed table whole ("a first copy";
  "snapshot" is a retired word on screen), then applies every change by key
  (`streams.apply_changes`: an insert or update replaces the row, a column a
  change does not carry keeps its value, a changed key moves the row, a
  delete removes it; rows in key order). A table without a primary key is
  followed as a log only and says so. The consume race is fixed (its own
  commit, `ccd56d9`), with a test that failed on the old code.
- **L2, four databases.** `live/postgres.py` (logical decoding, snapshot
  read through PostgreSQL's own text so a copied row and a changed one look
  the same), `live/mysql.py` (the row-based binary log, positions only at
  commit boundaries, columns named from the table when
  `binlog_row_metadata` is MINIMAL), `live/mongodb.py` (change streams with
  `updateLookup`, resume tokens), `live/sqlserver.py` (CDC tables read a
  whole number of transactions at a time). Each checks its requirements and
  names the fix.
- **L3, eight queues.** `live/kafka.py` (Kafka, and Event Hubs through its
  Kafka endpoint; partitions assigned from Pipewright's own offsets),
  `kinesis.py`, `pubsub.py` (REST, service-account JWT exchange),
  `pulsar.py` (reader from a saved message id), `rabbitmq.py`, `nats.py`
  (JetStream sequence), `mqtt.py` (persistent session, manual
  acknowledgement); every address checked by the outbound guard first.
  Guarantees: by position (Kafka, Event Hubs, Kinesis, Pulsar, NATS, the
  MySQL, MongoDB and SQL Server logs), by message id (PostgreSQL, Pub/Sub),
  at least once (MQTT; RabbitMQ and webhooks without ids, once with them).
- **L4, live recipes.** `live/windows.py` (pure: tumbling, hopping, sliding
  in the Azure Stream Analytics sense, session; watermark, lateness, drop or
  restate within a horizon) checked against a brute-force reference over
  random batches and arrival orders; `live_recipes.py` (row-by-row steps from
  a saved recipe, refused by name otherwise; a lookup through the maker's
  column policies; state, results and position in one transaction, proven
  by crashing a batch; outputs keep 30 days of windows).
- **L5, the runner.** `platform-live-runner` (`api_gateway/scripts/live_runner.py`)
  in `worker.sh`, both compose files and the Helm chart; a lease per feed;
  backoff to five minutes; the owner told once after five failures; events
  forgotten after `keep_events_hours` once every output has them; the log
  appended to, never rewritten. The ticker no longer reads feeds.
- **L6, in the product.** **Data → Live feeds**: the list, an add flow from
  each kind's declared settings with **Try these settings**, a page per feed
  (state, waiting events, throughput, guarantee and tier, what it keeps,
  live recipes with their latest windows, latest events, settings, start
  again, delete), the runner's heartbeat on System status and a warning on
  the live pages when it is down, a "live" activity kind, `live_source_failed`
  alerts, audit words, help (Data, glossary, API guide Example 5, What's
  new), the Python client and `docs/api/openapi.json`; migration 0062.
- **L7, proven.** `docker-compose.live.yml` and `scripts/check-live-servers.py`;
  a `live` CI job. 6 change-capture and 10 queue round trips; 36 lifecycle
  tests on SQLite and PostgreSQL; 39 window tests.

**Measured after** (same baseline, dev stack): the 1,000 rows are in the
table's dataset 1.0s after the feed is made; the raced change is stored;
insert, update and delete leave the dataset right (6.1s with saves every
10s); 20,000 changes are caught up in one pass in 8s (was 41 polls, 20
minutes); 120 Kafka messages read in 2s and summarised by minute; a webhook
post sent twice with one key is saved once.

**Faults found and fixed on the way** (each with a test that failed first):
the outbound guard refused `::1` with loopback allowed (Python counts it as
reserved); the window engine added a column's sum once per measure reading
it; lowest and highest mixed numbers and text; a PostgreSQL delete names its
key in the row, so deletes were skipped; a feed made with its tables broke a
foreign key on PostgreSQL (SQLite does not enforce them; the lifecycle tests
now run on both); the Kinesis test server repeats a record when the page
size shrinks, now never relied on.

---

## D2 — Performance (roadmap Phase 22)

**Why.** Phase 12 decides *where* work runs; this decides *how well*:
statistics, a cost model, the remaining rewrites, queries across sources,
caching, incremental runs, adaptive execution and resource limits.

### D2 specification (written 2026-10-15)

**Measured before starting** (`scratchpad/p20/baseline_d2.py`):

| | Now |
|---|---|
| Statistics | None. No row or distinct counts, no histograms; no plan carries an estimate |
| A 15-step recipe previewed over 1,000,000 rows | 3.93 s; editing step 14 runs all 15 again |
| A 40-column table, a recipe that keeps 2 | The pushed SQL lists all 40 columns in a nested `SELECT *` |
| A filter over a join | Stays above the join; only "merge filters" applies; `2 * 50` is not folded |
| Joining a PostgreSQL table to a MySQL table, or to a dataset | Not possible: a query runs against one connection |
| A recipe re-run after 1,000 rows are appended to 1,000,000 | Recomputes all 1,001,000 |
| 3,000 × 3,000 rows on one repeated key | 9,000,000 rows, +649 MB; 30,000 × 30,000 (900,000,000 rows) has nothing to stop it |
| Ten runs started in one project | All run at once; the queue is first come, first served |
| Memory per run | No ceiling |

**O1. Statistics.** Every dataset version records its row count and, per
column, the share of empty values, the distinct count, lowest and highest,
and a histogram (equal-count buckets for numbers and dates, the most common
values for text), computed when the version is written. Tables in a
connected PostgreSQL or MySQL database are described from the database's
own statistics (`pg_stats`, `information_schema`) or a sample, refreshed
daily by the ticker and after an import, and say which. The dataset page
shows them.

**O2. Estimates and a cost model.** `ir/estimate.py` estimates rows and
bytes for every node from those statistics (equality from distinct counts
and common values, ranges from the histogram, joins from the key's
distinct counts, groups from the product of distinct counts) and says how
it estimated each one; a guess is labelled a guess. The cost of reading,
moving and computing rows decides join order and how a query across
sources runs. The Studio's plan shows the estimate beside the actual rows
of each step.

**O3. The remaining rewrites.** Constant folding (only where every dialect
agrees), projection pruning (a scan reads only the columns used above it,
so the 40-column example selects 2), predicate pushdown through joins (to
the side the predicate reads; only the left of a left join), through
aggregates (on group columns) and union-alls, predicate transfer across a
join's equal keys (pull-up), limit pushdown through union-all, redundant
sort removal (a sort under a sort whose keys start with it, a sort under an
aggregate with no order-sensitive measure), common subexpressions computed
once, and join reordering by cost. Every one is proven by the differential
test: before and after, on both backends, value for value.

**O4. Queries across sources.** The SQL workbench gains **Across sources**:
one `SELECT` naming tables from several connections and datasets
(`connection.schema.table`, `datasets."Orders"`), parsed with `sqlglot` into
the IR. Each source runs the largest part it can, in its own dialect, with
filters and columns pushed into it; joins between sources run here. When
one side of a join is small, its keys are shipped to the other source as an
`IN` list (in batches of 1,000) instead of reading the whole table. The
plan says what each source ran, how many rows moved, and why.

**O5. Adaptive execution.** A query across sources fetches the smaller side
first; when its real row or key count is ten times off the estimate, the
rest of the plan is re-planned with the real number (an `IN` list becomes a
full read or the other way round, the join order changes), and the plan
says it switched. A join in any recipe counts its exact output rows from
the key counts before it builds them; one that would exceed the run's
memory ceiling stops before allocating, with the numbers.

**O6. Caching.** Results of a recipe's prefixes are kept, addressed by their
content (the input version, the reader's column policies, each step, the
versions of any dataset a step reads, and the frozen clock where a step
reads the time), in a bounded store. Editing step 14 of 15 reruns steps 14
and 15. Steps that are not deterministic (random sampling without a seed)
are never cached past.

**O7. Incremental runs.** A recipe can recompute only what changed. When
its input gained rows at the end (verified, not assumed) and every step
works row by row, only the new rows are computed and appended. With a
partition column chosen, only partitions whose rows changed are recomputed
and the rest reused from the last output, for recipes whose every step
keeps partitions apart; anything else runs in full and says which step
stopped it. Proven equal to a full run by a differential test.

**O8. Resource limits.** A project has a limit on runs at once (default 4):
queued work waits, a request beyond it is refused with the reason. Queued
work has a priority (started by a person, then scheduled, then backfills)
and the worker takes the highest first, skipping projects at their limit so
one busy project does not hold the rest up. Every run has a memory ceiling
(`RUN_MEMORY_LIMIT_MB`, default 2,048): the executor stops a run whose data
grows past it, with the step and the size, and on Linux the worker also
caps its address space so an allocation past it fails as a run error, not
a crashed worker.

**Done when.** Each baseline row has its measured "after": statistics on
every new version and on connected tables; estimates in the plan; the
2-of-40 query selects 2; the filter goes below the join; a PostgreSQL ×
MySQL × dataset query runs with an `IN` list and re-plans when the estimate
is wrong; editing step 14 of 15 on 1,000,000 rows is under a second; an
appended re-run computes only the new rows; the 900,000,000-row join stops
before allocating; ten runs in one project run four at a time with the
person's first; `npm run verify` is green with no `.env`; every page walked
at 1280 and 1024; CI green.
