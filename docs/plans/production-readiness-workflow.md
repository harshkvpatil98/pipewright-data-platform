# Production-Readiness Workflow

**Goal:** take every dimension of the 2026-09-23 adoption review
(`https://claude.ai/code/artifact/60390e70-34fd-42a8-bc23-05c2dd1a661f`) to
**9+/10**, and make Pipewright the product a company picks *over* the
established alternatives for data work — not by claiming more, but by being
the only honest, governed, spreadsheet-fast data platform that a business team
can run without a data engineer on call.

**Status:** P0–P7 done (P7 Time travel complete 2026-09-23, verified live with
`scripts/e2e/p7_time_travel.sh`); **P8 (BI & collaboration) is next**. One phase
executes per session-run;
the owner says **“continue”** to start the next. This file is the single
source of truth for what each phase contains; the session log in
`docs/HANDOFF.md` records what actually happened.

---

## Operating protocol (applies to every phase)

1. **Read first:** `AGENTS.md`, `docs/HANDOFF.md`, this file, and the phase’s
   section below. Re-verify any “current state” claim against the tree — a
   previous phase may have moved things.
2. **Implement the phase completely.** Nothing in the phase list is optional.
   If an item turns out to be impossible as written, implement the nearest
   honest alternative and record the delta in the phase report.
3. **Think past the list.** Each phase carries a *“Push further”* subsection —
   candidate improvements beyond the review. Evaluate each; implement the
   ones that fit the phase’s budget; queue the rest into later phases by
   editing this file. Every phase should ship at least one improvement nobody
   asked for.
4. **Quality gate — a phase is not done until every line is true:**
   - `npm run verify` fully green (ruff, pytest bundle, ESLint, tsc,
     production build).
   - **Zero pytest warnings** and zero new build/lint warnings. A warning is
     either fixed or explicitly filtered with a written justification at the
     filter site; “it was already there” is not a resolution.
   - Every new behaviour has a test (unit for logic, pytest for API, vitest
     for web logic). Every touched surface is **verified live in the browser**
     via the Chrome extension against the running dev stack, with the checks
     listed in the phase’s *Verify in browser* block.
   - No known defect, TODO, or half-wired state introduced by the phase
     remains. Pre-existing issues discovered en route are fixed if small, or
     appended to the correct later phase in this file if not — never silently
     dropped.
   - `docs/HANDOFF.md` ledger + session log updated; this file’s phase status
     updated.
5. **Ship:** commit in the repository’s style (imperative subject, body with
   evidence, test count) — author and committer
   `harshkvpatil98 <harshkvpatil@gmail.com>`, **no AI attribution of any
   kind** — and push the branch. Then report: what shipped, what the browser
   showed, scores moved, and stop for “continue”.
6. **Never regress the honesty invariants** (`AGENTS.md`): tier disclaimers,
   null-not-zero, stated refusals, single permission choke point, no model
   calls in the product runtime.

### Scorecard → target map

| Dimension | Review | Target | Reached by |
|---|---|---|---|
| Core data engine | 8.5 | 9.5 | P7 (versioning), P9 (pushdown wired, IR cutover) |
| Visual design | 8 | 9 | P0, P2 (fewer chips, checklist), continuous polish |
| Governance & audit | 7 | 9 | P6 ✅ |
| Feature coverage | 6 | 9 | P7 (time travel), P8 (BI), P9 (CDC/semantic) |
| Ease of first use | 5 | 9.5 | P0 + P2 |
| Language fit | 4 | 9.5 | P0 (pass), enforced by lint test thereafter |
| Operational trust | 4 | 9.5 | P0 (visibility) + P3 (packaged runtime) |
| Identity & access | 3 | 9.5 | P1 (core) + P4 (SSO/MFA) |
| Deployability | 5 | 9 | P5 |
| Collaboration | 6 | 9 | P1 (invites), P8 (comments, sharing) |

---

## P0 — Truth & trust *(status: **done** 2026-09-23)*

**Objective:** the product never contradicts itself, never dumps internals on
a first screen, and always tells the truth about background work. All ten
quick wins from the review land here.

### W1 · Language

- `apps/web/src/lib/labels.ts` (new): one canonical map for
  **type display names** (`string→Text`, `int/int64→Whole number`,
  `float/float64→Decimal number`, `date→Date`, `datetime/timestamp→Date &
  time`, `bool/boolean→True / false`, `decimal→Decimal (exact)`,
  `unknown→Unknown`) with `typeLabel()` falling back to Title-casing;
  **rule-type names** (`not_null→Must have a value`, `unique→No duplicate
  values`, `range→Within a range`, `regex→Matches a pattern`,
  `allowed_values→One of the allowed values`, plus fallback prettifier);
  **severity names** (`error→Error — quarantine failing rows`,
  `warn/warning→Warning — report only`); and `friendlyStepMessage()`
  translating step-validation strings (`config.conditions must be a non-empty
  list.` → `Add at least one condition to keep rows.`, generic fallback:
  strip `config.`, de-jargon “non-empty list”). Vitest: every canonical type
  and rule type resolves to a label with no underscores; fallbacks behave.
- Apply `typeLabel` in: Studio inspector schema panel, Studio column context
  menu, upload analyse “Read as” options, dataset detail schema list.
  Raw name stays visible as secondary (`title=` or muted suffix) — the
  truth is kept, the dialect is demoted.
- Apply rule/severity labels + `friendlyStepMessage` in Data Quality page and
  Studio banner respectively.
- Data Quality **column dropdown**: rule fields configured as `column` render
  a `<select>` of the chosen dataset’s columns (fetch preview columns);
  free-text remains only when no dataset is selected.
- Login subtitle → “Sign in to your Pipewright workspace.”
- Schedules dialog: **preset picker** (Every hour · Every day 09:00 · Every
  Monday 09:00 · First of the month 09:00 · Custom) writing the cron field,
  with a live plain-language echo of the chosen preset; Custom exposes the
  raw field exactly as today. Same options offered in the edit dialog.
- Studio save toast gains actions: **Run now** (POST the pipeline run, then
  link to the run) and **Schedule** (link to schedules page). Toast component
  already supports/gains an actions slot.

### W2 · Navigation truth

- Delete dead `components/layout/app-sidebar.tsx` + `lib/navigation.ts`
  (nothing renders them; they were the source of the “five ghost items”
  finding — record honestly that the live rail never showed them).
- Keep the `/datasets` `/pipelines` `/audits` `/testing` `/integrations`
  redirect routes (they are useful deep links, not pages).
- `buildRailSections` (app-frame): add **Administration** section for
  platform admins only — People (`/people`), Organisations
  (`/organisations`); they are currently unreachable except by URL.
- Rail defaults to **expanded** (labels visible) when no stored preference.
- `app-shell.tsx` breadcrumb: “Workspace” → the active project’s name (via
  `useActiveProject`), falling back to “Project” while loading.

### W3 · Operational visibility

- `service_workflows/queue.py`: add `oldest_queued_at(db)`; expose in
  `status.py` details as `oldest_queued_at` (ISO or null). Pytest: empty
  queue → null; queued rows → earliest `queued_at`.
- `apps/web/src/lib/runtime-health.ts` (new): pure
  `assessRuntime({queued, running, oldestQueuedAt, dueNow, now})` →
  `{level: 'ok'|'stalled', message}` — *stalled* when work is queued/due,
  nothing is running, and the oldest waiter is >15 min old. Vitest covers the
  matrix (fresh queue ok; 33-day-old queue stalled; running suppresses).
- Home: **Background work** card (queued n · running n · schedules due n ·
  “oldest has waited 33 days” in danger tone when stalled) sourced from
  `/status`; Platform-health panel sorts non-healthy modules first (never
  hidden by the `slice(0,8)`) and shows a one-line reason for degraded
  observability (“n open incidents (m critical)”) derived from its details.
- Status-bar health chip becomes a **link to `/system-status`**, and its
  label carries the count (“1 module degraded”).
- Workflows page + Schedules page: warning banner via `assessRuntime` —
  “Nothing is picking up background work — n run(s) waiting, oldest since
  {date}. Start the worker (see System status).”
- Workflow run rows: queued runs show a **waiting-since chip**, danger-toned
  past 15 min.
- System status page: known counter keys render as labelled stat chips
  (“5 open incidents · 1 critical”, “39 metrics recorded”), the
  `drivers_not_installed` array collapses to “41 optional drivers not
  installed ▸”, and the raw JSON moves behind a per-row “raw” toggle.
  Scheduler note stays — reworded to lead with what an operator should do.

### W4 · Warning debt → zero

- Fix JWT test keys shorter than 32 bytes (InsecureKeyLengthWarning) across
  gateway/auth tests.
- Central, documented warning policy for the two upstream pydantic
  `schema_json` shadow warnings (public API field name is a contract; the
  shadowed `BaseModel.schema_json` is deprecated upstream): filter exactly
  those messages in `apps/api-gateway/src/api_gateway/warnings.py` (imported
  at app start) + pytest `filterwarnings`, each with a justification comment.
- Sweep the pytest summary to **0 warnings**; add
  `-W error::DeprecationWarning`? — no: keep signal, enforce “0 in summary”
  via the gate instead.

### Push further (evaluate, implement what fits)

- Health chip tooltip listing degraded modules. *(cheap — do)*
- `Needs attention` status-bar item links to the failing-rules view. *(do)*
- Command palette gains People/Organisations once in rail (automatic). 
- Persist “raw” toggle state on system status. *(skip unless trivial)*

### Verify in browser (Chrome extension, running stack)

Home: card shows the real stalled queue; chip links; degraded module visible
with reason; get-started steps link. Studio: friendly banner text; save toast
actions work (Run now actually queues). DQ: dropdown lists the six Acme
columns; labels human. Schedules: preset writes cron; banner present (worker
absent). System status: no raw JSON visible by default. Rail: labels by
default; People/Organisations present for admin; breadcrumb shows “Acme
Retail Demo”.

### Exit gate

Protocol §4 + this phase’s browser list. **Score claims after P0:** Language
4→8.5 · Ops trust 4→7 (visibility only; packaged runtime lands in P3) ·
Ease 5→6.5 · Design 8→8.5.

---

## P1 — Identity core *(status: **done** 2026-09-23)*

**Objective:** pass page one of a security questionnaire; onboard and offboard
without `curl`.

- **Password change** (`POST /auth/me/password` current+new, bcrypt≥
  current cost, sessions invalidated via `token_version` column on users —
  migration 0031) + Settings UI. **Admin reset**: one-time reset code
  (`POST /auth/users/{id}/reset-code`, hashed, 30-min TTL, single use) +
  redeem route on the login screen; People row action “Generate reset code”.
- **Invite flow:** People → “Invite person” (username, email optional, role,
  org) creating a deactivated-until-first-password account with a one-time
  activation code (same mechanism as reset); Organisations → “New
  organisation”, “Rename”.
- **API tokens:** `api_tokens` table (name, hash, scopes: read|write|admin,
  last_used_at, revoked_at); `Authorization: Bearer pw_…` accepted by the
  auth dependency; Settings “API tokens” panel (create-once-shown, list,
  revoke); OpenAPI docs link. Audit every token action.
- **Session hygiene:** active-session list (jti registry), sign-out-all;
  configurable expiry via env surfaced in Settings (read-only display).
- **Display name** field (nullable) on users; greeting and People use it.
- **Admin action log:** People/Org mutations write governance audit entries.
- Security one-pager `docs/security.md` (auth model, storage encryption,
  backups, disclosure contact) linked from Settings.
- *Push further:* login rate-limit (per-user+IP, in-DB sliding window);
  password strength meter (zxcvbn-lite heuristic, no dependency).
- **Tests:** full pytest coverage incl. token-version invalidation, reset-code
  single-use, token scoping refusals; vitest for strength meter.
- **Browser:** change own password, invite “analyst2”, sign in with reset
  code, mint+use+revoke an API token via curl against :8001.

---

## P2 — Guided first win *(status: **done** 2026-09-23)*

**Objective:** three non-technical testers reach a scheduled, validated
pipeline unaided in <20 min.

**Delivered:** project checklist (live-ticking, dismissible) with the chip-wall
regrouped under a Workspace menu (Build/Govern/Operate/Publish); merged
entry-points (Add data · Connect a source, Register dataset under advanced);
Home “Get started” mirrors the first project’s real checklist state; one-click
“Create a demo project” seeding a full worked example (file → pipeline → rule
→ schedule → chart → dashboard) from the same service functions a user’s
clicks call, deletable like any project, covered by an end-to-end test;
save-pipeline naming prompt and inline rename; first-run mini-tours for Data
quality and Schedules (the first-project checklist is itself the guidance the
spec’s “checklist tour” asked for, so a redundant tour on top of it was
deliberately not added — the review’s warning against over-guidance); type
fidelity via a stored `canonical_type` and a cross-surface test. Resumable
upload is carried into P3 (see below).

- **Project checklist** replaces the chip-wall on empty projects
  (Add data → Shape it → Guard it → Schedule it), each step one primary
  action, live-ticking (derived from counts), dismissible once complete;
  chip-wall regroups under a “More” menu (Build/Govern/Operate/Publish).
- Entry-point merge: **Add data** (upload) · **Connect a source**
  (extraction); “Register dataset” moves under advanced.
- Home “Get started” card mirrors checklist state of the active project.
- **Sample workspace**: seed script + “Create demo project” on empty Home
  (orders CSV, one pipeline, one rule, one schedule, one chart+dashboard) —
  built from the curated Acme flow; deletable like anything else.
- Save-pipeline **naming prompt** (pre-filled), pipeline rename inline.
- Extend tours: checklist tour on first project; DQ and Schedules mini-tours.
- Type fidelity: Studio/inspector shows ingest-spec canonical types
  (single source: dataset schema endpoint gains `canonical_type`); the
  cross-surface test walks upload→studio→publish asserting one vocabulary.
- Upload modal: wire the **resumable chunked API** (progress bar, resume on
  retry, 25 MB soft-cap lifted to backend limit; keep honest max from
  config); analyse screen unchanged. *(Carried into P3 — it is an operational
  robustness concern, not a first-win one, and P3 already owns the resumable
  backend surface; the plain upload path is unchanged and honest about its
  limit in the meantime.)*
- *Push further:* “Explain this step” inline help drawn from tool registry
  docs; empty-state illustrations per surface (SVG, tokened).

---

## P3 — Operational backbone *(status: **done** 2026-09-23)*

**Objective:** kill the worker mid-demo; the UI says so within a minute and
recovers alone.

**Delivered:** runtime heartbeats (workflow worker + schedule ticker each beat
a `runtime_heartbeats` row every loop) give ground truth; `assessRuntime`
consumes them first and falls back to queue-age inference. Packaged runtime:
`scripts/worker.sh` supervises both processes, `dev.sh` starts them, docker
compose gains `app`/`worker` profiles with restart policies. A System-status
Runtime panel and the Home card show per-component heartbeat + queue depths. A
stalled queue (>30 min, no beating worker) opens a "runtime" incident from the
ticker and auto-resolves on drain. Workflow-run failures now notify in-app like
every other run, and the first-run checklist offers Slack/email targets.
Dashboard sharing is finished end to end (public `/shared/dashboards/{token}`
viewer, robots-noindex, immediate revocation). Real cross-project `/runs`
(status filter) and `/datasets` (search) replace the redirects, scoped by the
project-access rule. Upload sessions moved to a durable `upload_sessions` table
so a gateway restart resumes rather than orphans (this absorbed the resumable
item carried from P2). *Deferred stretch:* the dead-letter view for failed
workflow nodes with re-run — a genuine enhancement, not a gap in the objective,
recorded here rather than silently dropped.

- **Packaged runtime:** `scripts/worker.sh` + supervised processes in dev
  (`dev.sh` starts gateway + workflow worker + schedule ticker) and compose
  profiles (`app`, `worker`) with restart policies; runtime writes
  `runtime_heartbeats` (component, beat_at, host) each loop — replaces the
  P0 inference with ground truth (assessRuntime consumes heartbeats first,
  falls back to inference).
- System status “Runtime” panel: per-component last heartbeat, host, queue
  depths; Home card upgraded likewise.
- **Queued-age incidents:** observability opens an incident when stalled >30
  min; auto-resolves on drain.
- **Notifications on by default:** run failure + critical incident →
  in-app always; first-run checklist offers Slack/email target creation.
- **Dashboard sharing shipped:** public token viewer route
  (`/shared/dashboards/{token}` — read-only, no auth, project-scoped data
  via server-side token lookup, revocation immediate, robots-noindex) + UI
  share button with copy-link; or if a public route is vetoed at execution
  time, remove tokens entirely — no third state.
- **Cross-project operator views:** real `/runs` (all projects’ recent runs,
  filter by status) and `/datasets` (search across projects) pages replacing
  two redirects; palette entries.
- Upload sessions move to durable store (table + storage chunks) so a
  gateway restart doesn’t orphan uploads. *(from review §7 known gaps)*
- *Push further:* dead-letter view for failed workflow nodes with re-run.

---

## P4 — Enterprise identity *(status: **done** 2026-09-23)*

**Delivered:** TOTP two-factor — enrol (server-rendered QR + secret), confirm-
before-active, login two-step (ticket → TOTP or recovery code), regenerate,
disable, admin reset; RFC 6238 with no third-party TOTP dependency, tested
against the RFC vectors. OIDC SSO wired end to end — /auth/sso/status, /start
(discovery + PKCE + durable one-time state), /callback (state verify, code
exchange, JWKS-verified ID token, claim mapping, JIT provisioning with
group→role and no silent demotion, session cookie), "Continue with SSO" on the
login screen; the RS256 signature path is tested against a matching JWKS, only
the transport is faked. SAML remains deliberately unimplemented (the signature-
verification refusal stands) and its status is surfaced by /auth/sso/status.
SCIM-lite deactivate-on-absence job (`scim-sync`) offboards directory-managed
accounts safely (only auth_source="sso", never the last admin). Reference:
`docs/enterprise-identity.md`.

*Not delivered here (honest scope):* the OIDC/SAML wire protocol is unverified
against a live Auth0/Okta/Entra tenant — none is available in this environment;
point it at a real provider to confirm. Inbound SCIM 2.0 push and the "push
further" per-org session/expiry policy are deferred.

- **OIDC SSO** end-to-end against a real IdP (Auth0/Okta dev tenant):
  discovery, PKCE, JIT-provision with default role, group→role mapping
  option; login screen “Continue with SSO” when configured.
- **TOTP MFA** (enrol QR, verify, recovery codes, admin reset).
- **SAML** via `xmlsec` (signature-verified only — the existing refusal to
  ship unverified SAML stands), Okta+Entra tested profiles.
- SCIM-lite: deactivate-on-absence sync job spec (documented; implement if
  time allows).
- *Push further:* per-org session/expiry policy.

---

## P5 — Deployability & scale *(status: **done** 2026-09-23)*

**Delivered:** a Helm chart (deploy/helm/pipewright — per-component images/
resources, pre-upgrade migration Job, /api-and-/ ingress so the SSO cookie
carries, optional HPAs, operator-owned secrets, tag required so never "latest");
a production docker-compose.prod.yml with a Caddy TLS proxy and a managed-DB
escape hatch; a CI workflow that builds+pushes the gateway and web images to
GHCR on a version tag. docs/operations.md runbook (upgrade, backup/restore with
the verify drill, scaling, sizing, observability). An opt-in slow-query log
(DB_SLOW_QUERY_MS) that logs only statements past a threshold, with the request
correlation id, off by default. A dependency-free perf baseline
(scripts/perf-baseline.py) hitting the ten hot endpoints with a --budget-ms CI
gate, first numbers recorded. /metrics (Prometheus) and correlation-id tracing
already existed and are now documented.

*Deferred (push further):* SBOM + pip-audit/npm audit CI gate. *Note:* Helm
templates were validated by YAML/brace checks and docker compose by
`docker compose config` — no `helm` binary was available to run `helm template`
against a cluster.

- Production compose (gateway+worker+web+postgres+proxy w/ TLS notes),
  **Helm chart** (values for images, env, resources, HPA hints), images
  built+pushed in CI on tag.
- `docs/operations.md`: upgrade, backup/restore (drill the existing
  `backup.sh --verify` into the doc), scaling notes (sticky uploads until P3
  durable store, scheduler runtime ids), sizing table.
- Perf baseline: k6-style script (plain python/locust-free) hitting the ten
  hot endpoints; record numbers in the doc; regression budget in CI
  (optional job).
- Structured log/trace pass: request-id everywhere (exists) + slow-query log
  toggle; `/metrics` documented for Prometheus.
- *Push further:* SBOM + `pip-audit`/`npm audit` gate in CI.

---

## P6 — Governance depth ✅ done (2026-09-23)

- **Audit Center** (real `/audits`): cross-project stream, filters, CSV/JSON
  export, retention setting; admin actions included (from P1). ✅
- **Policy simulation:** “view as role/user” preview for row/column security
  on any dataset (extends existing security-preview). ✅
- **Approvals UX:** reviewable diff view for versioned definitions; request
  changes with comment (uses existing governance comments API). ✅
- **Erasure lifecycle** implemented against the settled decisions in
  `docs/plans/phase-18-review-requirements.md` §2 (correction vs destructive
  erasure; no silent success) — pre-work for P7’s immutable history. ✅
- Catalog: ownership/certification editing, glossary term linking from
  dataset pages. ✅
- *Push further:* data-classification tags (PII auto-suggest from
  service-intelligence) surfaced in catalog + policies. — **deferred** to a
  later pass; the catalog now carries free-form tags and stewardship, and PII
  auto-suggest is a service-intelligence feature better sized on its own.

---

## P7 — Time travel (Phase 18 of the product roadmap) ✅ done (2026-09-23)

Execute `docs/plans/phase-18-review-requirements.md` in full — it is already
the accepted requirements set (producers inventory, immutable snapshots,
erasure interplay, replay determinism with recorded execution context, GC
protocol, authorisation matrix, acceptance list). This is the engine
differentiator: **versioned datasets, `AS OF` queries, diffs, rollback,
deterministic replay**. Ships in increments (storage → publication →
temporal reads → diff/rollback → replay), each gated.

**Increment 1 — version storage & publication: ✅ done (2026-09-23).**
- `content_digest` primitive (`shared_python.storage`): stable `sha256:<hex>`
  fingerprint of published bytes.
- `dataset_versions` table (migration 0038, schema only per settled decision
  #5): one immutable row per materialisation; `version_number` 1-based,
  monotonic, `(dataset_id, version_number)` unique; content hash + snapshot
  metadata; never updated or renumbered (decision #6).
- §5 transaction-ownership seam: `apply_dataset_materialization_success`
  (flush, caller owns commit) + `finalize_…` (commit-owning wrapper the four
  producers still call), so head advance and version publication land — or roll
  back — together. All four producers (uploads, extraction, transformations,
  quality quarantine) record a version with the content digest.
- Read surface: `GET …/datasets/{id}/versions` (viewer, §6-correct) + a Version
  history panel on the dataset page. Storage keys kept out of the API (§4/§5).

**Increment 2 — temporal reads + §1 decisions: ✅ done (2026-09-23).**
- Versions store the preview they published (migration 0039); `GET
  …/versions/{n}` and `GET …/versions/{n}/preview` read a dataset **as of** a
  version (viewer role); “View data” per version in the history panel.
- §1 per-producer identity write-up in `docs/plans/phase-18-decisions.md` —
  including the honest statement that every producer creates a new dataset per
  run today, so multi-version history arrives with rollback; extraction keeps
  dataset-per-run (watermark lives on the job).
- Verified **live in the browser**: upload → version 1 recorded with a
  digest that matches the bytes (checked byte-for-byte), history panel with
  current pill, View-data modal showing the snapshot, PII scan → suggested
  classification tags → Add as tags → steward + certify → Save, persisted and
  reflected in catalog facets. Dev DB migrated to 0039; dev gateway restarted
  from this checkout (port 8100, CORS incl. :3002).

**Increments 3–6 — ✅ done (2026-09-23).** Diff (decision #7 identity rules)
and rollback (append-a-version, decision #6) with their history-panel actions;
erasure reconciled with immutable snapshots (correction appends, destructive
scrubs every version and re-digests, blocked never skipped); the §4 pin +
two-step prune protocol with a `dataset_versions` retention policy (migration
0040); the §3 frozen evaluation clock and recorded execution context on every
run; deterministic replay with a six-way honest answer and output pins on the
run audit page; `AS OF` SQL over stored versions (decision #8) with a Query
action and "Query as of" control; the §6 matrix pinned centrally
(`EDITOR_SEGMENTS`, `query` read-only). **Live acceptance:**
`scripts/e2e/p7_time_travel.sh` — 39/39 against a gateway started from this
checkout, plus browser verification of every new surface. Decisions and the §8
answers are in `docs/plans/phase-18-decisions.md`; limitations that remain by
design (extraction dataset-per-run, SQLite dialect for temporal SQL, no
cursors on history, `today()` in UTC) are in `docs/HANDOFF.md` §7.

---

## P8 — BI & collaboration

- Dashboard builder v2: grid layout (drag/size), global filters, text tiles,
  auto-refresh; chart types rounded out (pie/donut sparingly, tables,
  big-number with delta).
- **Comments everywhere** (existing `/discussion` API): datasets, pipelines,
  dashboards; @mentions → notifications.
- Email invites (SMTP config + templates) building on P1 codes.
- Report formats: PDF via headless print pipeline if a maintained pure
  approach exists; otherwise print-CSS + “Print to PDF” affordance done
  properly and stated honestly.
- Scheduled report delivery to Slack target.
- *Push further:* dashboard subscriptions (“email me this every Monday”).

---

## P9 — Market-decider depth

- **Pushdown wired into runs** (Phase 12 cutover) + IR-only executor cutover
  (both pre-approved in HANDOFF as deliberate separate decisions — this
  phase makes them, with the differential suites as the gate).
- **Streaming/CDC** (product Phase 20): Postgres logical replication first,
  webhook receiver second; honest tiering like connectors.
- **Semantic layer** (product Phase 19): metrics defined on the IR,
  consumed by charts and the workbench.
- Optimizer groundwork (product Phase 22) as evidence allows.

---

*Maintained by the phase sessions themselves. When scope moves between
phases, move the bullet — never duplicate it.*
