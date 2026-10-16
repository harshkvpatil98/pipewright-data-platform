# Tools and extensibility

**Date:** 2026-10-16, after D1 and D2 (`live-data-and-performance.md`).
**Purpose:** finish the last two roadmap v2 phases: **Phase 16, the
transformation tool library**, which shipped its machinery and 173 tools in
2026-08 and named seven families as not built, and **Phase 23,
extensibility and ecosystem**, which has not started.

**Status:** E1 (the tool library) done, 2026-10-16; E2 (extensibility) in progress.

Each phase measures first, says what it will deliver and when it is done,
then records what shipped. The rules in `AGENTS.md` and the A0 vocabulary
apply: recipe, check, import, deliver, schema change; sentence case; no
em-dashes; UK spelling; `count_of`, never "(s)".

---

## E1 — The tool library (roadmap Phase 16) *(done 2026-10-16)*

**Why.** The Studio is meant to be the only tool an analyst opens. Today a
running total, a rank within a group, an anti join, a percentile, a random
sample, a distance between two places, a forecast, a lookup with a default
or turning a step off cannot be done in a recipe at all; people leave for a
spreadsheet or a notebook, and the recipe stops being the record of what was
done to the data.

### E1 specification (written 2026-10-16)

**Measured before starting** (the registry and `GET /transformations/tools`
on the dev stack):

| | Now |
|---|---|
| Tools | 173 in 11 categories, plus 23 step types |
| The roadmap's list | 447 entries in 23 families; the Phase 16 notes name window, statistical, ML, geospatial, fuzzy matching, enrichment, reshape and recipe management as not built |
| Tool search for 29 everyday tasks | Finds nothing for 26: running total, moving average, previous row, percentile, anti join, fuzzy join, random sample, train/test split, distance, point in polygon, correlation, cluster, forecast, one-hot, holiday, lookup, fill forward, interpolate, assert unique, golden record, geocode, unit convert, transpose, SQL, UUID, disable a step. "rank" finds only Sort; "t test" finds only Filter |
| The IR | No window node; joins model semi, anti and cross but the join step offers inner, left, right and outer |
| The aggregate step | 11 functions; no percentile, mode, correlation, weighted average, list or product |
| Recipes | A step cannot be turned off or duplicated; no saved templates of one's own, no parameters, no branches |

**T1. Windows.** A `Window` node in the IR: partition columns, an
ordering with explicit null placement, and functions over a frame (rows or
peers, from unbounded or N before to the current row). Both backends run it;
the pandas backend keeps the input's row order. Functions: row number, rank,
dense rank, percent rank, cumulative distribution, ntile, lag, lead, first,
last and nth value, and sum, average, lowest, highest, count, product and
standard deviation over the frame; exponential moving average, rolling
correlation and session numbering run here only. **What pushes down is what
cannot differ:** rank, dense rank, percent rank, cumulative distribution and
aggregates over peers give one answer however ties arrive; row number, lag,
lead, ntile, first/last/nth value and row-counted frames depend on the order
of tied rows, so they stay local, as `first` and `last` already do. The
optimiser never moves a filter below a window unless it reads only
partition columns; the estimator keeps the row count; an incremental run
by partition is allowed when the window is partitioned by the partition
column and refused otherwise; lineage reads the node. Queries across sources
accept window functions in the select list. Tools (about 30): every window
entry in the roadmap, plus running average, difference, percent change,
percent of total, normalise 0 to 1, z-score, top N per group and fill
forward and backward.

**T2. Aggregates and joins.** The aggregate step gains mode, count of
empties, nth, list, text joined with a separator, variance, percentile,
quartile, range, product, any true, all true, correlation, covariance and
weighted average; each that has an exact SQL equivalent lowers
(`PERCENTILE_CONT`, `CORR`, `COVAR_SAMP`, `BOOL_OR`), proven against SQLite
and PostgreSQL. The join step gains full, cross, semi and anti. New tools
that read another dataset (all saved under `right_dataset_id`, the key
bundles, promotion, lineage, impact, previews, runs and the kept-results
cache already follow): an as-of join (nearest earlier or later match within
a tolerance, by key), a range join (a value between two columns), a fuzzy
join (similarity at or above a threshold, by edit distance, sound or
tokens), merge side by side by position, intersect, except, and append by
column name. The tool form gains a dataset picker.

**T3. The everyday families.** Every remaining entry in rows, columns,
reshape, text, numeric, dates, conversion, missing data and cleansing:
among them keep the last N, skip the last N, custom sort order, reverse,
shuffle with a seed, insert and delete a row, keep or remove rows that fail
to convert, transpose, promote and demote headers, split by position and by
pattern, split to rows, nest columns, cross-tab, add a constant column,
negate, ratio, robust scaling, equal-frequency bins, currency and unit
conversion, holidays (the `holidays` package, by country and region),
fiscal periods, a date spine and filling missing dates per key, from a
time zone and to UTC, to decimal, to JSON, to a list, linear and spline
interpolation, dropping mostly-empty columns, transliteration, language
detection (common-word frequencies over 20 languages, with its confidence
and a refusal under three words), address standardising and parsing (UK and
US rules, others left whole), currency codes, swapped columns, standardised
units and lookup-based standardising.

**T4. Checks inside a recipe, matching, and lookups.** Assertions (not
empty, unique, in a set, in a range, matches a pattern, of a type, every key
found in another dataset, row count, no duplicates, always increasing, sum
equals, fresh, schema matches, distribution stable against the previous
run, and a formula) pass the data through unchanged and either stop the run
naming the rows, or warn. Deduplication and matching (keep the most
complete, mark and count duplicates, fuzzy deduplicate by edit distance,
sound or tokens, cluster similar values, merge a cluster to its commonest
spelling, survivorship rules, golden records) use the **same matching code
as the Assistant's entity resolution**, moved to `shared_python/matching.py`
so there is one answer to one question. Lookups: from a dataset (first match,
never more rows), with a default, by several columns, fuzzy, a hierarchy
(ancestors, level, top), a generated date dimension, historical currency
rates (as-of), a calendar, domain from email, company from domain against a
dataset, country from an IP address against a ranges dataset, time zone from
coordinates, and geocoding through a service the operator configures.

**T5. Statistics, machine learning, sampling and places.**
- *Statistics* (28): describe, correlation and covariance matrices,
  histogram, frequency table, cross-tabulation, outliers by IQR, z-score,
  MAD and isolation forest, normality, one- and two-sample and paired t
  tests, ANOVA, chi-square, Mann-Whitney, Kolmogorov-Smirnov, simple,
  multiple and logistic regression, residuals, confidence intervals, sample
  size, seasonal decomposition, autocorrelation, a trend test, change points
  and distribution fitting. Each answers with its method, its statistic, its
  p-value or confidence, and a sentence saying what that means.
- *Machine learning* (18): k-means, hierarchical and density clustering,
  PCA, anomaly scores, ARIMA, exponential smoothing and trend-plus-season
  forecasts with intervals, KNN and iterative imputation, naive Bayes and
  decision-tree classification, feature importance, one-hot, ordinal and
  target encoding, TF-IDF and a similarity matrix. **Where the model lives:**
  in the step. It is fitted on the step's input every run, seeded, so a run
  and its replay agree; nothing is stored between runs, and every result
  states the method and a measure of how good it is (silhouette,
  cross-validated accuracy, a backtest error). No language model is called.
- *Sampling* (12): random, stratified, systematic, cluster, top N per group,
  train/test and time-based splits, split by value or condition, split into N
  parts, reservoir and balanced samples, every one seeded.
- *Places* (14): parse coordinates (decimal or degrees, minutes and
  seconds), distance (haversine, and Vincenty on the WGS84 ellipsoid),
  bearing, within a radius, point in polygon (a shape, or a dataset of named
  regions), nearest neighbour in another dataset, bounding box, centroid,
  area, buffer, geohash both ways and GeoJSON. Shapes are WKT in a
  `geography` column; haversine lowers to SQL exactly, the rest run here.

**T6. Code, metadata and the recipe itself.**
- *Code*: a SQL step (a SELECT over the working data, parsed into the IR, so
  it pushes down, has lineage and is checked like any step), a Python step
  through the notebook sandbox (disabled with the reason where the sandbox
  cannot hold, as cells are), a JSON query step (a jq subset), an inline
  lookup table, a text template, HTTP enrichment (an allowed-hosts list the
  operator sets, through the outbound guard, one call per distinct value,
  bounded and cached in the run; such a recipe is never kept or run
  incrementally, and says so), and a regular-expression tester in every tool
  form that takes a pattern.
- *Metadata*: steps that set a column's description, tags, classification
  and personal-data marking, the dataset's owner and a glossary link on the
  recipe's output when it runs; step notes; a generated data dictionary;
  schema snapshots and comparison.
- *The recipe*: turn a step off and on, duplicate a step, save steps as a
  template of one's own (per project) and apply it, parameters (`{{name}}`
  in any setting, with defaults, set per run by a person, a schedule, a
  workflow or the API), branches of a recipe and merging a branch back
  through the co-editing merge rules, comparing two recipes, running a
  recipe's steps on another dataset, and splitting a dataset into one recipe
  per value.

**T7. Every roadmap entry accounted for.** `tools/coverage.py` lists all
447 entries of the roadmap's list and names, for each, the tool, step
setting or Studio feature that does it. A test fails if an entry is missing,
names a tool or step that does not exist, or names a feature without a test
behind it. The generated reference (`docs/transformation-tools.md`) gains
the new families, and the help says what each family is for.

**Done when:** every family above is built and in the reference with an
executed example; every new tool passes the library's structural tests
(empty, all-null, single row, example, lineage); every pushable new function
or node is proven equal against SQLite and PostgreSQL; the 29 searches above
each find the right tool first; `coverage.py` accounts for all 447 entries;
`npm run verify` and the CI-environment suite pass; every page is walked at
1280 and 1024; and a rehearsal on the dev stack builds a recipe using a
window, a lookup, a check, a forecast and a parameter, runs it, and compares
its numbers with PostgreSQL's.

### E1: what shipped (2026-10-16)

**379 tools in 22 categories** (173 before), the IR's 201 functions and a
`Window` node with 23 window functions, the aggregate step's 27 functions
and the join step's eight kinds. `tools/coverage.py` maps **all 447
entries** of the roadmap's list: 364 to tools, 57 to a step setting that
`test_tool_coverage.py` runs on a sample table, 25 to a Studio or recipe
feature with the test that exercises it, and one, the custom plugin, to
E2. The test reads the list from `roadmap-v2.md` itself, so the two
cannot drift.

| | Before | After |
|---|---|---|
| Tools | 173 in 11 categories | 379 in 22 |
| The roadmap's 447 entries | 7 families named as not built | Every one done by a tool, a step setting or a feature, by test; the plugin is E2's |
| The 29 everyday searches | 26 found nothing, 2 the wrong tool | All find what they mean first, on the server and in the Studio, against the real catalogue (`test_tool_search.py`, `palette-search.test.ts`) |
| The IR | No window node | `Window`, pushed down where ties cannot change the answer |
| The aggregate step | 11 functions | 27, each lowered where exact and proven |
| The join step | Inner, left, right, outer | Plus full, cross, semi and anti (EXISTS) |
| Pushdown proof | Per function | Every tool that pushes down, run on SQLite and PostgreSQL against the engine (`test_tool_sql_agreement.py`) |
| A recipe | No off switch, no copies of steps, no parameters | Steps turn off, duplicate, take notes, group (a macro) and take threads; parameters per run; templates, branches and merges, comparison, the steps on another dataset, one recipe per value |

By part:

- **T1, windows.** The `Window` node, run by both backends with SQL's
  rules; ranks and totals over peers or a whole partition push down, the
  order-dependent rest stays here. Rewrites, estimates, the planner, join
  reordering, incremental runs, provenance and lineage know it; queries
  across sources take window functions. 31 window and analytic tools.
- **T2, aggregates and joins.** 16 more aggregate functions, one
  implementation for the step and the engine; full, cross, semi and anti
  joins; as-of, range and fuzzy joins, side by side, intersect and except,
  each reading another dataset as `right_dataset_id`, which kept results,
  replay pins, lineage and impact follow. A dataset picker in tool forms.
- **T3, the everyday families.** Rows, columns, reshape, text, numbers,
  dates, conversion, missing data and cleansing, including holidays by
  country and region, fiscal periods, a date spine, interpolation,
  transliteration, language detection, addresses (UK and US rules),
  measurements and reversible tokens. A formula filter keeps rows where a
  formula holds, and pushes down.
- **T4, checks, matching and lookups.** 15 checks inside a recipe that
  stop the run naming the rows, warn, or mark them to quarantine;
  deduplication and matching on `shared_python/matching.py`, which the
  Assistant shares; lookups from a dataset with a default, a hierarchy,
  calendar columns, historical rates, company from domain and country
  from IP.
- **T5, statistics, machine learning, sampling and places.** 28
  statistics with method, statistic, p-value and a sentence each; 18 models
  fitted in the step, seeded, with a stated measure of how good they are;
  12 seeded samples and splits; 17 place tools on WKT, haversine pushed
  down.
- **T6, code, metadata and the recipe.** SQL over the step's input
  (parsed into the IR), sandboxed Python, a jq subset, an inline lookup
  table, templates, an HTTP lookup per value (allowed hosts, server-side
  secrets, retries, pacing; never kept or run incrementally, and it says
  so) and geocoding through a configured service. Metadata steps write the
  output's catalogue entry on each run; a data dictionary as Markdown or
  CSV. Parameters, templates, branches with a merge preview and conflicts,
  comparison, the steps on another dataset, one recipe per value, a thread
  on one step, a regex tester answered by the engine's own expressions,
  and token reveal for an administrator. In the Studio: the More menu's
  dialogs, a step's power, duplicate, group, note and comment buttons,
  right-click a cell to keep or drop rows like it, and a schema check that
  fills in the columns as they are now.
- **T7, accounted for.** `tools/coverage.py` and its test; search ranks
  a query that names a tool first and treats a single letter as a whole
  word; the palette leads with steps or tools by whichever matches better;
  the command palette finds the open step's actions; the Studio's tests rank
  against a checked-in copy of the catalogue that a server test keeps
  current.

**Faults found and fixed on the way** (each with a test): PostgreSQL
divided whole numbers as whole numbers and stopped on a zero; text sorted
by collation there and by character codes here; a multi-key sort placed
every key's empties where the first key said; five aggregates were
declared with no implementation; ROUND rounded half to even here and half
away from zero in every database; a text-to-number cast gave empty, 0 or
an error depending on where it ran; a date function over text failed in
PostgreSQL; SUBSTR with two arguments wrote SQL no database parses; a
local tool's warnings were dropped; a forecast read periods as nanoseconds
since 1970; saving parameters reset the shared copy and threw away
everyone's unsaved changes; a malformed parameter was a 500; a merge
preview was audited as a merge and the regex tester filled the audit log;
"t test" found the train/test split first, "distance" found Buffer, "trim"
found Trim quotes, "remove duplicates" found the fuzzy remover and "zip
code" found the address parser; an HTTP lookup was refused incremental
runs with the wrong reason; the Studio's tests loaded two copies of React,
so a shared component's hooks found none. The rehearsal found four more: a
step's problem was shown under whichever step was open (the refusal now
says which step it came from), a tool step that works on no one column read
"Not set up yet" however it was set up, a failing check said "Rows 1, 2, 3,
4 and 5 and more" (now "and 265 more") and named itself "Check" rather than
by its title, and the retired recipe addresses redirected from inside a page
(now from the web's configuration).

**Deliberately not done.** The custom plugin entry is E2's (X1). Steps in
a group are grouped by a shared name and stay ordinary steps: a group
saved as a template is a copy, so changing the template later does not
change the recipes it was added to. A Python step runs only where the
notebook sandbox holds (not on macOS), and says so.

---

## E2 — Extensibility (roadmap Phase 23)

**Why.** A product does what its makers built; a platform does what its
users need. Today a connector, a tool, a formula function or a chart type
can only be added by changing this repository; work in dbt, Airflow, Alteryx,
Informatica, SSIS, Talend or Power Query has to be rebuilt by hand; a team
that manages infrastructure as code has a command line but no Terraform; a
template or a metric definition cannot be shared beyond its project; and
another product can embed a dashboard but not the Studio.

### E2 specification (written 2026-10-16)

**Measured before starting:**

| | Now |
|---|---|
| Adding a connector, tool, formula function or chart type | Only by editing this repository |
| API tokens | Read, write or admin, for everything the person can reach, never expiring |
| OpenAPI, Python client, `pipewright` command | Exist (A8 Y3) |
| Terraform | None |
| Work from another tool | None of the seven formats is read |
| Sharing | Project bundles (A8 Y2); three built-in recipe templates; metrics only within a project |
| Embedding | Dashboards only (A8 Y4); framing sites listed once per deployment |

**X1. The plugin SDK.** `packages/plugin-sdk` (`pipewright-plugin-sdk`) is
a published, versioned interface (SDK 1): a plugin is a Python package with
a `pipewright.plugins` entry point, or a folder, that declares a manifest
(name, version, publisher, SDK version, what it contributes) and contributes
any of: connectors (a code connector or a REST manifest), tools, formula
functions and chart types. The gateway loads plugins named in
`PLUGINS_ENABLED` at start, refuses one built for another SDK version or
failing its conformance checks, with the reason, and never loads one
silently. **The same suites as first-party code:** a plugin's connectors pass
the connector conformance suite, its tools the tool library's structural
tests, its functions the function catalogue's checks (null in, null out,
types declared, a lowering only where proven), and its chart types the
chart validator. Chart types are declarative (marks, scales and encodings
the web renders with its own SVG), so no plugin code runs in a browser.
`pipewright plugin new` writes a starting plugin and `pipewright plugin
check` runs every suite on it before installing. Administration lists the
plugins, what each added, its tier and its check results.

**X2. The API, as code.** Tokens can be limited to projects and given an
expiry, and the audit log names the token. A Terraform provider
(`clients/terraform`, Go, the plugin framework) manages projects, members,
connections (secrets write-only), recipes (from their YAML), schedules,
checks, workflows and API tokens, with data sources for projects, datasets
and connections, `terraform import` for each resource, and acceptance tests
that run against a real gateway in CI. Publishing it to the Terraform
Registry is a public act and waits for the owner.

**X3. Bringing work in.** Importers for a dbt project (models, refs,
sources, seeds and schema tests), an Airflow DAG file (read, never run:
tasks, dependencies, schedule), an Alteryx workflow (`.yxmd`), an
Informatica PowerCenter mapping (XML export), an SSIS package (`.dtsx`), a
Talend job (`.item`) and a Power Query M script. Each produces editable
recipes, checks and workflows through the ordinary APIs, and a report of
what converted, what did not and why, step by step; nothing is converted
approximately. SQL goes through the same SQL-to-IR translator as the SQL
step. The fixtures are public examples where a licence allows (named, with
their licence) and files written here from the vendors' published formats
otherwise, which the report and the help say.

**X4. A library to share through.** A Library page lists recipe templates
by industry, connectors and metric definitions, each with its publisher, its
version, its verification tier and what installing it changes. Installing
adds the item to a project through the ordinary APIs; publishing turns a
project's template, connector manifest or metric into a signed package
(Ed25519) another deployment can install. An operator can add a remote
index (`LIBRARY_INDEX_URL`), fetched through the outbound guard and refused
when a signature does not verify against a key the operator trusts.
Pipewright's own items say "made by Pipewright, tested here".

**X5. The Studio, embedded.** An embed can now be a Studio: a partner's
server signs a short-lived token (HS256 with the embed's own secret) naming
its own user, and that person edits recipes in one project as a guest with
the role the embed allows, never seeing the rest of the workspace. Embeds
are white-labelled (name, logo, colours, light or dark) and say which sites
may frame them, per embed (closing the per-deployment gap in HANDOFF §7). A
small script (`/embed/pipewright-embed.js`, no library) mounts it and
passes messages both ways: the host can open a recipe and set the theme,
and hears when a recipe is saved or a run finishes.

**Done when:** a plugin from outside the repository adds a connector, a
tool, a function and a chart type that work on every surface and pass their
suites, and a broken one is refused with its reason; `terraform apply`
builds a project with a connection, a recipe, a schedule and a check against
the dev stack and CI, and `terraform plan` afterwards shows no changes; each
importer turns its fixtures into recipes that run and match the source's
expected output, with an honest report; a template, a connector and a
metric go from one project to another through the Library and a signed
package, and a tampered package is refused; a partner page embeds the
Studio, edits and runs a recipe as a guest, and cannot reach anything else;
`npm run verify` and the CI-environment suite pass; every page is walked at
two widths; and each part is rehearsed on the dev stack.

### E2: what shipped (in progress)

| | Before | After |
|---|---|---|
| Adding a connector, tool, formula function or chart type | Only by editing this repository | A plugin (SDK 1) adds any of them, held to the suite Pipewright's own pass (X1) |
| API tokens | For everything the person can reach, never expiring | Limited to projects and expiring, named in the audit log, held to the owner's role (X2) |
| Terraform | None | `clients/terraform`, acceptance tests against a real gateway in CI (X2) |
| Work from another tool | None of the seven formats is read | All seven, with a report part by part, each checked against the source's own answer (X3) |

By part:

- **X1, plugins.** `packages/plugin-sdk`, `PLUGINS_ENABLED`, the suites as
  functions (`tools/conformance.py`), **Admin → Plugins**, `pipewright
  plugin new` and `check`. The roadmap's custom-plugin entry has its test.
- **X2, the API as code.** Tokens limited to projects and expiring
  (migration 0067); the Terraform provider for projects, members,
  connections, datasets, recipes, schedules, checks, workflows and tokens,
  with import and data sources; a `terraform` CI job. Fault fixed: an API
  token skipped the project role guard.
- **X3, bringing work in.** `apps/api-gateway/src/api_gateway/conversions/`:
  a converter per format makes a `Conversion` (what it reads, datasets
  from its data, recipes, checks, workflows and a report), and
  `apply.py` previews it or makes it through each service's own create
  functions, by key, skipping names already used and what reads them.
  SQL (dbt models, Airflow SQL tasks) goes through the SQL step's
  translator: the first table is what the recipe reads, each join a
  **Join as SQL does** step (`join.sql`, new), the rest one SQL step, a
  CTE another part joins a recipe of its own; set operations use the
  combine tools. The flow formats (Alteryx, Informatica, SSIS, Talend,
  Power Query) build a stream of steps, each compiled and run on an empty
  frame before it is accepted, with each tool's own expression language
  parsed to the formula language (`expressions.py`, printed by
  `formula/printer.py`) and its rules for empty values written in.
  Anything the vendor's documentation does not pin down is refused with
  the reason; the three places it is silent and a part still converts
  (an all-empty Alteryx Sum, where SSIS Sort and tSortRow put an empty
  value) are said in the report and the help. **Bring work in** on the
  Recipes page, `POST /projects/{id}/conversions[/preview]`, and
  `pipewright convert`.

  Proof: each fixture (written here from the vendor's documented format,
  as each fixture's README says) converts and runs; the dbt project's
  every model equals SQLite running the model's SQL, its checks pass as
  its dbt tests do and a broken one fails; the others equal results
  worked by hand from the documented rules; through the API, every
  format's made recipes give the same rows as the in-memory run, and the
  dbt workflow runs to the end. 179 importer tests, 408 printer tests.

  Faults found on the way and fixed in the platform: the SQL step ignored
  `QUALIFY`, `DISTINCT ON`, a named `WINDOW`, `TABLESAMPLE`, a `NATURAL`
  join and the other clauses it does not run, and now refuses them by name; a recipe's result read back lost values ("NA",
  "unknown", -99 became empty, text that looked like numbers became
  numbers), so files Pipewright writes are now read with the types they
  were written with (`service_ingestion/written.py`); `MOD` with a
  negative side differed between a local run and a pushed-down one; the
  unique check had no way to let empty values repeat, as dbt's does.
