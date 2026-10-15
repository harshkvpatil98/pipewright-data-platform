# Contracts and working together

**Date:** 2026-10-15, after the adoption-readiness sequence (A0–A9) closed.
**Purpose:** finish two roadmap v2 phases that were left partial:
**Phase 19's data contracts** (the semantic layer half shipped in
production-readiness P9) and **Phase 21's real-time collaboration**
(comments with @mentions shipped in P8). Both can be built and proven on
one machine, with nothing waiting on a vendor account. Phase 20 (queues and
streaming windows) and Phase 22 (statistics and a cost model) stay partial,
and Phase 23 has not started; `docs/HANDOFF.md` §8 keeps that ledger.

**Status:** C1 (data contracts) done 2026-10-15; C2 (working together) next.

Each phase measures first, says what it will deliver and when it is done,
then records what shipped. The rules in `AGENTS.md` and the A0 vocabulary
apply: recipe, check, import, deliver, schema change, sentence case, no
em-dashes, UK spelling.

---

## C1 — Data contracts (roadmap Phase 19, second half) *(done 2026-10-15)*

**Why.** A dataset other people rely on can change shape under them. The
roadmap's words: a producer writes down what the data promises; consumers
follow it; a change that breaks the promise is stopped at the run that
would have made it, not found by a consumer three weeks later.

### C1 specification (written 2026-10-15)

**Measured before starting** (dev stack, `scratchpad/p19/baseline.py`):

| | Now |
|---|---|
| A recipe edited to drop a column others use | Ran and succeeded; the dataset's next version silently lost `email`; no schema change recorded, no notification |
| An import whose source loses a column | Recorded as a schema change and a warning on the run; the new data replaces the old regardless |
| Promises about a dataset | None. Checks test values after the data has landed; schema changes are noticed, never agreed |
| Who relies on a dataset | Column impact analysis exists (recipes, checks, workflows); nothing lists the people or the dashboards that depend on it |

**What a contract is, in the product's words.** "A contract is a promise
about a dataset: which columns it has and what is in them, how many rows,
and how often it gets new data. New data that breaks it is stopped before
it replaces what people are using, and everyone who follows it is told."

**K1. The promises.** One contract per dataset, with an owner (the person
answerable for it) and a description. Its terms:

- *Columns*, each with a kind (Text, Whole number, Decimal number, Date,
  Date & time, True / false, or Any), and optionally: always filled, no
  repeats, only these values, between a lowest and highest number.
- *Other columns*: new columns may appear (the default), or only the
  promised ones.
- *Rows*: at least, at most, and no more than a stated share fewer than
  the last version.
- *New data*: at least every so many hours.

A contract is written from the current data in one click (every column with
its kind; "always filled" where nothing is empty now; at least one row),
then edited. Saving one that the current data already breaks says so at
once. Every change is a new version with a sentence saying what changed.

**K2. Enforced where data lands.** Recipe runs, imports and stream saves
check the dataset's contract after working out the new data and before
storing it. With "Stop data that breaks it" (the default) the run fails
with the reasons, the current data stays, and the run log says "Checked the
contract"; with "Let it through and warn" the data lands and the problem is
recorded. One evaluator decides, reusing the checks' own evaluators for
values (`service_quality.rules`), so a contract and a check can never
disagree about what "always filled" means. Rolling back to a version that
breaks an enforced contract is refused with the reasons, and the version
history says so before anyone tries. Erasing a person's data is never
stopped (it is a legal duty) but is recorded when it breaks a promise. An
upload always makes a new dataset, so it has no contract to keep.

**K3. Problems, once.** A broken contract is one problem per source and set
of reasons while it lasts ("seen 3 times"), resolved when new data keeps
the contract again. Overdue new data is a problem the worker records once
and resolves when data arrives. The owner and everyone following the
contract are told when it breaks, when it is kept again and when its terms
change, in the app and through any alert channel that takes "A contract was
broken or changed" (`data_contract`). Notifications are written with the
problem and sent by the worker after commit, as metric alerts are.

**K4. Followers and who relies on it.** Anyone in the project, a viewer
included, can follow a contract: choosing to be told changes nothing in the
project. The contract lists what reads the dataset (recipes, checks, charts,
dashboards through their charts, metrics, deliveries, workflows), derived
when asked, never stored. Removing or loosening a promise shows which
recipes and checks read that column before it is saved, from the existing
impact analysis.

**K5. Where people see it.** A **Contracts** tab under Trust lists every
contract in the project with whether it is kept, its open problems and its
owner. Each dataset page shows "Contract kept" or "Contract broken" and
opens the dataset's contract page: the promises, follow, recent problems,
what relies on it and the history. A recipe whose result has a contract
says so in the Studio, and names a promised column the preview no longer
has before the recipe is run.

**K6. The rest of the product knows about it.** Audit phrases for every new
route, error messages in the product's words, the Python client and
`docs/api/openapi.json`, the help (trust page, glossary, API guide), the
activity stream, and the bundle export (contracts travel with a project's
recipes and checks).

**Done when.** The baseline's breaking recipe run is stopped with the
reason, its dataset keeps `email`, the owner and a follower are told once,
and the next good run resolves the problem; an import that loses a column
is stopped the same way; overdue data opens and closes a problem; the
Trust tab, dataset chip, contract page, Studio notice and rollback warning
all show it; `npm run verify` is green with no `.env`; every page walked at
1280 and 1024 with no problem; CI green.

### What shipped

- **K1, promises.** `service_quality/data_contracts.py` and migration 0060
  (`data_contracts`, `_versions`, `_followers`, `_problems`, `_events`). A
  contract per dataset with an owner, a description, "stop" or "warn", and
  terms: per column a kind, always filled, no repeats, only these values,
  lowest and highest; other columns allowed or not; rows at least, at most,
  and the largest fall; new data every so many hours. One click drafts it
  from the current data (kinds, "always filled" where nothing is empty, at
  least one row), and saving says at once whether the current data keeps
  it. Every change is a version with what changed in sentences.
- **K2, enforced where data lands.** Recipe runs (`run.py`, stage
  "checking the result against its contract"), imports (`extract.py`) and
  stream saves (`streams.py`) call `check_new_data` after working out the
  new data and before storing anything; a broken enforced contract fails
  the run with 409 and the reasons, and the dataset keeps its head. The
  verdict travels to the version seam (`apply_dataset_materialization_success`,
  `contract_verdict=`), which records a let-through problem or resolves
  answered ones in the version's own transaction. Rollback asks first and
  is refused with the reasons; both erasure paths are never stopped and
  record what they break. Values are judged by the checks' own evaluators;
  a whole-number column with an empty value (which pandas holds as
  decimals) still counts as whole numbers. Reasons give counts, never
  values, because a contract is visible to people a column policy hides
  values from.
- **K3, problems once.** One problem per source and set of broken terms
  while it lasts (times seen counted), superseded when the same source
  breaks something else, resolved when that source's data keeps the
  contract. Overdue data mirrors the dataset's one freshness promise (the
  contract writes it; the worker's freshness sweep judges it), opened and
  closed by the worker. Messages (broken, overdue, kept again, changed)
  are written as events and sent by the worker after commit to the owner
  and followers, or the project's acting people when there are none, and
  to alert channels that take `data_contract`; the person who changed a
  contract is not told about their own change.
- **K4, followers and what relies on it.** Following is a viewer's right
  (`PERSONAL_SEGMENTS` in the permission rules). The contract lists the
  recipes, checks, charts, dashboards, metrics, scheduled deliveries and
  workflows that read the dataset, worked out when asked; dropping a
  promise shows the column impact analysis before saving.
- **K5, pages.** Trust → **Contracts** (list, "Add a contract"), the
  dataset's contract page (problems now, what it promises, what relies on
  it, earlier problems, history; follow, check now, change, remove), the
  editor, a "Contract kept/broken" chip and a menu entry on the dataset
  page, a notice in the Studio naming promised columns the preview no
  longer has, and a warning in the restore dialog with the button disabled
  when an enforced contract would refuse it.
- **K6, the rest of the product.** Audit phrases for the five new writes;
  activity gains a "Contracts" kind; bundles carry contracts (named after
  their dataset, skipped when the target dataset has one); the Python client
  and `docs/api/openapi.json`; help (trust, glossary, API guide example 4,
  what's new, overview).

**Found and fixed on the way.**

- Every failed recipe run and import kept only "Waiting to start." in its
  log (13 of 13 failed recipe runs and 19 of 19 failed imports in the dev
  database). Producers append to one list and passed that same list on
  each write, so SQLAlchemy never saw a change after the first; the run
  service now stores a copy each time (`_snapshot`).
- The first live save of a contract with a chart reading the dataset failed
  on PostgreSQL (`DISTINCT` over dashboard rows with JSON columns), which
  SQLite allows. The query uses a subquery, and every contract test now runs
  on PostgreSQL too, in a schema of its own, wherever CI provides one.
- Six strings in run logs and warnings used retired words ("Schema drift
  detected", "Dataset artifact state persisted", "rule", "misconfigured");
  `test_error_words.py` now reads run-log lines and warnings, which are
  passed by position and were never checked.

**Measured at the end.** The baseline's breaking recipe, live: refused with
409 ("The column 'email' is missing."), the dataset kept `email`, the bell
said so once, and the next good run resolved it ("keeps its contract
again"). An import from PostgreSQL after the source table lost `email`:
refused the same way, its log ending "Stopped while checking the rows
against the contract." Overdue data opened a problem within one worker
tick and closed 50 s after new data. 77 pages walked at 1280 and 1024 with
no problem; `npm run verify` green with no `.env` (6,573 Python passed,
837 web).

**Not done here, and stated.** A contract is about one dataset in this
deployment; there is no contract published to another deployment or held
at the source. Followers are people; a downstream recipe is listed as
relying on a dataset but is not itself notified (its owner can follow).

---

## C2 — Working together (roadmap Phase 21, the rest)

**Why.** Two analysts in the same recipe today overwrite each other without
knowing it, and a viewer who sees a mistake can only describe it in a
comment.

### C2 specification

Written at the start of C2, measured first; the baseline above already
shows the first defect: two saves of the same recipe from the same starting
point both succeed, and the second silently drops the first's step.

---

*Maintained by the phase sessions themselves. When scope moves between
phases, move the bullet; never duplicate it.*
