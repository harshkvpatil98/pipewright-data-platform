# Tools and extensibility

**Date:** 2026-10-16, after D1 and D2 (`live-data-and-performance.md`).
**Purpose:** finish the last two roadmap v2 phases: **Phase 16, the
transformation tool library**, which shipped its machinery and 173 tools in
2026-08 and named seven families as not built, and **Phase 23,
extensibility and ecosystem**, which has not started.

**Status:** E1 (the tool library) and E2 (extensibility) in progress.

Each phase measures first, says what it will deliver and when it is done,
then records what shipped. The rules in `AGENTS.md` and the A0 vocabulary
apply: recipe, check, import, deliver, schema change; sentence case; no
em-dashes; UK spelling; `count_of`, never "(s)".

---

## E1 — The tool library (roadmap Phase 16)

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
