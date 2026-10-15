# Contracts and working together

**Date:** 2026-10-15, after the adoption-readiness sequence (A0–A9) closed.
**Purpose:** finish two roadmap v2 phases that were left partial:
**Phase 19's data contracts** (the semantic layer half shipped in
production-readiness P9) and **Phase 21's real-time collaboration**
(comments with @mentions shipped in P8). Both can be built and proven on
one machine, with nothing waiting on a vendor account. Phase 20 (queues and
streaming windows) and Phase 22 (statistics and a cost model) stay partial,
and Phase 23 has not started; `docs/HANDOFF.md` §8 keeps that ledger.

**Status:** C1 (data contracts) and C2 (working together) done 2026-10-15.

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

## C2 — Working together (roadmap Phase 21, the rest) *(done 2026-10-15)*

**Why.** Two analysts in the same recipe today overwrite each other without
knowing it, and a viewer who sees a mistake can only describe it in a
comment.

### C2 specification (written 2026-10-15)

**Measured before starting** (dev stack and the code):

| | Now |
|---|---|
| Two people saving one recipe | Both saves from the same starting point succeed; the second silently drops the first's step |
| Seeing who else is there | Nothing: no presence anywhere |
| Editing together | The Studio holds the recipe in the browser and saves it whole; another person's change is seen only on reload, and saving over it loses it |
| A viewer who spots a mistake | Can read, cannot comment (operator and up) and cannot propose; the Studio has no way to propose a change |
| Recipe change requests | Recipes have no snapshot or restorer: a proposed recipe change has no "before", its summary reads "Changed .", and approving one would fail with "'pipeline' changes cannot be applied automatically" |
| "Changes need approval" | The help describes it; nothing can switch it on (the project setting is ignored) |
| Comments | Flat, one level, per object; no replies and nothing about a cell |
| A dataset's history | "History" opens a record of where it came from; nothing lists what happened to it over time |

**W1. No silent overwrites.** A recipe has a revision. A save that names
the revision it started from is refused with 409 when someone saved since,
saying who and when; the Studio always names it. Anything else that changes
a recipe (an approved suggestion, a restored version, the API) moves the
revision on too.

**W2. Editing a recipe together.** Each recipe has one shared working copy,
merged on the server: the steps are a sequence of stable ids ordered by
fractional positions, step settings are last-writer-wins per setting, a
removed step is a tombstone, and every change carries a Lamport stamp, so
changes merge the same in any order (`service_transformations/coedit.py`
and its TypeScript twin, held together by shared fixtures and a convergence
test). The Studio sends its changes as they happen and asks for others'
every two seconds; others' changes appear without a reload, and undo never
takes back someone else's work, because their changes are applied to the
whole undo history. Saving writes the shared copy; a change made outside
the Studio resets it and keeps the person's unsaved steps as their browser
draft, with a message saying why.

**W3. Who is here.** People with the Studio open on a recipe show at its
top, and each person's initials sit on the step they have open; someone
who closes the page or goes quiet for 20 seconds disappears.

**W4. Suggest instead of save.** Recipes get a snapshot and restorer, so
their change requests have a "before", a summary in words and can be
approved. Someone who may not edit (a viewer or operator), or anyone in a
project whose changes need approval, sees **Suggest these changes** where
Save was: it becomes a change request with a title and note. Editors see
"2 suggestions" in the Studio and on Approvals, open one to see the steps
added, removed and changed, and accept (applied as a new version, credited
to its author) or decline with a note; the author is told either way. The
project setting "Changes need approval" can be switched on by an admin.

**W5. Threads on a cell.** Comments take replies and an anchor: a column,
and a row by its identifier column's value (or its row number in that
version, said so). On the dataset page a cell with a thread is marked, and
any cell can start one; a thread resolves as a whole, and mentions notify
as before.

**W6. What happened to a dataset.** The dataset's History page gains a
feed, newest first: each new version (who or which run, rows and columns
before and after), schema changes, check results, contract problems,
alerts, incidents, comments and changes to its settings, paged.

**Done when.** Two browsers on one recipe see each other within two
seconds, both edit without either losing work, and an old revision's save
is refused with the reason; a viewer's suggestion is accepted by an editor
and applied as the recipe's next version; a cell thread is started,
replied to and resolved; the dataset feed shows the run that made each
version; `npm run verify` green with no `.env`; every page walked at two
widths; CI green.

### What shipped

- **W1, no silent overwrites.** Recipes carry a `revision`, stable step ids
  and who saved last (migration 0061). `PATCH` with `expected_revision`
  from an older revision is refused with 409: "Ann Lee saved this recipe at
  … after you opened it". Every save is in the recipe's history.
- **W2, editing together.** `service_transformations/coedit.py` and
  `apps/web/src/features/studio/coedit.ts`: a CRDT of stable step ids at
  fractional positions, last-writer-wins registers per setting, position,
  removal and name, Lamport stamps; `coedit-fixtures.json` holds the cases
  both sides must agree on, merged in every order. The server keeps the
  merged copy and the batches (`recipe_shared_copies`,
  `recipe_edit_batches`); the Studio sends changes every 300 ms and asks for
  others' every 2 s (`use-recipe-editing.ts`). Undo is per person and
  selective: it takes back a change only while the register still holds it.
  Saving writes the shared copy; a change from outside (an accepted
  suggestion, a restored version, the API) starts a new epoch, says why, and
  offers back what the person had not saved. A convergence test runs 40
  trials of three people editing at random.
- **W3, who is here.** `service_governance/presence.py`: one row per tab,
  a beat every 5 s, gone after 20 s or on closing; initials in each
  person's colour at the top of the Studio and on the step they have open.
- **W4, suggestions and approval.** Recipes have a snapshot and restorer
  (`service_transformations/versioning.py`), so their change requests have
  a "before", a summary and can be accepted. `POST …/pipelines/{id}/suggest`
  is open to a viewer; editors review step by step (`recipe-diff.ts`) in the
  Studio's drawer and under Approvals (now Accept and Decline, Accepted and
  Declined), and the author is told either way. Reviewers hear of a new
  suggestion (a new "Suggestions and reviews" notification category). An
  admin can switch on "Changes need approval".
- **W5, threads on a cell.** Comments take `parent_id` and an anchor (a
  column, and a row by its identifier's value or its number in a version);
  threads resolve as a whole, a reply reopens one, and everyone in a thread
  hears of a reply. The dataset page's rows mark commented cells, any cell
  opens its threads, and "Comment on a cell" chooses one from the keyboard.
- **W6, what happened to a dataset.** `api_gateway/dataset_activity.py`:
  versions and what made them, failed runs, checks, schema changes,
  contracts, alerts, incidents, comments and settings changes, paged; on the
  dataset's History page.

**Found and fixed on the way.**

- Rehearsing with three people: the Studio compared settings with
  `JSON.stringify`, so the shared copy (keys sorted) and the saved recipe
  (keys as written) looked different: Bob's Studio said "Unsaved changes"
  after Ann saved, and a suggestion listed a step as changed into itself.
  Comparisons use `stableJson` now, with a test.
- A page's first two presence requests raced to insert the same row, and the
  loser failed (seen in the browser as a CORS error); the same race could
  hit two Studios opening a recipe together. Both now find the other's row;
  the test fails on the old code three times out of three on PostgreSQL.
- The accessibility suite found the Studio previewing without end: the
  editing hook made a new list of steps each render. Memoised, with a test
  that fails without it.
- The golden path found the first save of a new recipe reopening as an empty
  new recipe, because the leave guard still held the page; the page now
  marks it saved first.
- Recipe change requests could never have been applied (no restorer), and
  "Changes need approval" could not be switched on; both work now.
- Approvals described a recipe suggestion as "Added steps json[step type=sort
  rows]", the generic snapshot diff. Governance now asks each kind of thing
  to describe its own changes (`register_summariser`); a recipe says "Adds a
  sort rows step (step 2).", in its history too.
- The dataset feed now says when a version gained or lost columns, not only
  rows.

**Measured at the end.** Live, three browsers on one recipe: each saw the
others within one presence beat, Bob's rename reached Ann's Studio in 842
ms, Ann's undo left Bob's rename alone, both said "Saved" after Ann saved,
Vic (a viewer) saw "Suggest", his suggestion listed only the rename, and
Ann declined it with a note that reached him. Idle, a Studio asks for the
shared copy every 2 s and says it is there every 5 s, and nothing else.
`npm run verify` green with no `.env` (6,608 Python passed, 848 web); every page walked at 1280 and 1024 with no problem; the
golden path and accessibility suites pass against the dev stack.

**Not done here, and stated.** Changes reach others by asking every two
seconds, not by a push channel: simple behind any proxy and on any number
of gateways, at the cost of up to two seconds. Presence and co-editing are
in the Studio; dashboards and the SQL workbench are still edited one person
at a time, with saves as before. A cell thread names its row by an
identifier column only when the profile found one; otherwise by its number
in one version, which the thread says.

---

*Maintained by the phase sessions themselves. When scope moves between
phases, move the bullet; never duplicate it.*
