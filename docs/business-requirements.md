# Pipewright
## Business Requirements Document

**From recurring data preparation to governed, repeatable workflows**

Version 1.0 | 23 September 2026 | Business review draft

Repository baseline: `79eb302` (includes the first three P2 increments)

This document describes the business purpose, target users, supported workflows, current requirements and complete documented future scope of Pipewright. It distinguishes implemented capabilities from partial delivery, deployment dependencies, unverified integrations and speculative ideas.

Prepared for the product owner, business sponsors, analysts, data teams, platform operators and implementation partners.

<!-- PAGE -->
# Document guide

## Purpose and authority
This is a consolidated BRD for the application as inspected on 23 September 2026. It is a business review draft, not a signed delivery contract. The target segments, proposed success measures and rollout recommendations are business interpretations of the product; they are not evidence of paying customers, market research or approved service levels.

Current capability claims use the checked-out code, executable registries, handoff and the three P2 commits through `79eb302`. Future scope uses the production-readiness plan, product roadmap and accepted time-travel requirements. Later concurrent development is outside this fixed baseline. Recorded tests are not proof that every external integration was exercised for this BRD. [S01-S05, S15]

## Status vocabulary
| Label | Meaning in this document |
|---|---|
| Available | Implemented in the current repository; deployment prerequisites may still apply. |
| Partial | A usable part exists, but an important end-to-end path or part of the stated scope is unfinished. |
| Conditional | Code exists but needs a driver, credential, operating-system capability or running service. |
| Planned | Documented future work, not delivered in the current baseline. |
| Candidate | Optional improvement or exploratory idea; not a committed release item. |

## Reading map
The first part explains the business, users and main workflow. The requirement catalogue describes what users can do now. The roadmap register covers every documented future feature family, including gaps inside phases labelled complete. Acceptance, rollout, risks and the source register close the document. Appendices list all 173 current transformation tools and connector readiness by category.

**Priority convention:** Must = essential to the stated business workflow; Should = substantial usability or governance value; Could = optional expansion. Priority describes business importance, not a promised delivery date. Individual production phases retain their documented scope.

{{CONTENTS}}

<!-- PAGE -->
# Business purpose

## The main use case
**A business or data analyst repeatedly receives data from spreadsheets, operational databases and business systems, prepares a trusted dataset, and delivers it to reporting or another system on a controlled schedule.** Pipewright turns those repeated preparation steps into saved recipes and workflows with previews, quality checks, run history, access controls and traceable outputs.

For example, a retail operations team combines order extracts with customer data each morning. An analyst standardises dates and customer identifiers, removes duplicate records, joins reference data, calculates measures and quarantines invalid rows. An operator runs or schedules the workflow. A manager consumes charts or exported results. A steward can inspect the origin of a number and review changes to the recipe.

## Business problem
- Manual spreadsheet preparation is repeated, difficult to reproduce and dependent on individual knowledge.
- Scripts, extracts, quality checks, publishing and incident handling are distributed across disconnected tools.
- Ambiguous source formats, inconsistent types and silent coercion create plausible but incorrect results.
- Teams lack a common view of who changed a workflow, what failed and which downstream assets may be affected.
- Analysts need familiar data manipulation; engineers need repeatability, controlled access and operational evidence.

## Intended value
Pipewright combines a spreadsheet-style preparation surface with reusable pipelines and data operations. Its business promise is faster preparation with visible rules and evidence: show uncertainty, explain unsupported operations, preserve type meaning and make each run inspectable.

The product is an internal data preparation and operations platform. It can feed existing BI and database systems. It is not presently a complete replacement for an enterprise warehouse, master-data management suite, enterprise identity provider or mature streaming platform.

## Position at the baseline
The application includes broad batch ingestion, preparation, quality, governance, reporting and operations capabilities. Production-readiness P0 and P1 are recorded as complete; P2 is partially delivered through canonical type display, a project checklist and pipeline naming. Time travel, semantic metrics, streaming, live co-editing, advanced optimization and the wider ecosystem remain future work. Runtime packaging and the rest of guided onboarding remain adoption work. [S01-S03, S15]

<!-- PAGE -->
# Business objectives and measures

The following objectives express what an adopting organisation should gain. Except for the onboarding target explicitly present in P2, numerical targets below are proposed pilot criteria requiring sponsor approval. No measured ROI, throughput or availability is asserted.

| ID | Business objective | Measure and acceptance approach |
|---|---|---|
| BO-01 | Reduce repeated preparation effort. | Baseline hands-on minutes for a recurring dataset; propose at least 50% reduction after the recipe is stable. |
| BO-02 | Make first use achievable for analysts. | P2 target: three non-technical testers independently reach a scheduled, validated pipeline in under 20 minutes. |
| BO-03 | Improve confidence in delivered data. | Every pilot production dataset has an owner, agreed checks and a visible latest result; track invalid rows and escaped defects. |
| BO-04 | Make business changes reviewable. | Every governed recipe change has a proposal, decision and actor history; no unreviewed bypass in acceptance tests. |
| BO-05 | Reduce unnoticed operational failure. | Monitor queue age, failed runs and incident response; P3 target: worker loss visible within one minute and recovery demonstrated. |
| BO-06 | Broaden safe self-service. | Count recurring workflows maintained by analysts; measure support interventions and permission failures without exposing data. |
| BO-07 | Make delivery repeatable. | Record run, output and publish outcomes; reconcile row counts and business totals at the destination. |
| BO-08 | Make historical results reproducible. | Planned P7: reproduce a pinned run using its recorded inputs and evaluation context, or return an explicit incompatibility. |

## Stakeholder outcomes
**Business sponsor:** shorter time to usable data and fewer recurring manual controls. **Analyst:** quick previews, understandable errors and reusable transformations. **Data engineering:** fewer bespoke integration scripts and controlled escape hatches. **Governance:** accountable definitions, access rules and evidence. **Operations:** clear ownership of failures and background processing.

## Measurement plan
Select two or three recurring workflows and record their current handling time, frequency, row counts, failure modes and reconciliation steps before migration. Measure the same factors after adoption. Separate setup effort from recurring effort and record driver, credential and environment constraints. Savings may be calculated from measured time saved multiplied by actual run frequency and an organisation-approved labour cost; this BRD assumes none of those values. [S02]

<!-- PAGE -->
# Target customer groups

These are recommended target segments inferred from the implemented workflow and roadmap. They are not claims of validated market demand or existing customers.

| Segment | Typical need | Fit and adoption condition |
|---|---|---|
| Business operations and finance teams | Repeat spreadsheet consolidation, reconciliations, cleansed exports and monthly reporting. | Primary user group when a technical owner can operate the deployment and validate required connections. |
| Analytics and BI teams | Prepare trusted datasets; profile inputs; publish to databases, Power BI or Tableau; explain results. | Strong fit for batch preparation and reviewable business logic. Vendor publishing needs real credentials and validation. |
| Small and midsize organisations with lean data teams | Replace repeated scripts and manual file handling with shared workflows. | Primary adoption hypothesis; guided onboarding and packaged background runtime remain planned. |
| Enterprise departmental data teams | Controlled self-service within a project and tenant boundary. | Conditional fit: identity integration, operational hardening and governance depth need deployment-specific acceptance. |
| Data consultancies and implementation partners | Build repeatable preparation processes for clients and document them. | Project separation is available; embedded and white-label commercial distribution are future scope. |
| Data engineering and platform groups | Maintain connectors, extraction jobs, SQL workflows, schedules and incident handling. | Essential enabling group and likely technical evaluator, even where analysts are the daily users. |

## Illustrative business domains
Retail and commerce: product, order and customer preparation. Finance operations: reconciliation and controlled reporting inputs. Sales and marketing operations: standardisation of CRM and campaign exports. Supply chain: inventory and supplier datasets. HR operations: controlled workforce reports. These are example use cases, not packaged industry solutions or compliance certifications.

## Buying and rollout roles
The likely sponsor is a head of analytics, finance operations, business operations or data platform. A technical owner evaluates hosting, integration and recovery. Security and governance owners assess access, secrets, retention and audit requirements. Department managers nominate dataset owners and approve business definitions.

## Where the current fit is limited
Teams requiring turnkey SAML/MFA, proven high-volume low-latency streaming, comprehensive historical replay, regulated certifications, universal connector readiness or maintenance-free hosting must treat those as adoption gates. The repository does not establish a pricing model, managed SaaS offering, contractual support model or production SLA.

<!-- PAGE -->
# Users and responsibilities

| Persona | Main work in Pipewright | Desired outcome |
|---|---|---|
| Business/data analyst | Upload and inspect files; prepare data in Studio; use formulas and tools; preview and save recipes. | Trusted output without rewriting the same cleanup every reporting cycle. |
| Analytics engineer/data engineer | Configure sources and extraction; create joins and workflows; use SQL, notebooks and recipe code. | Repeatable pipelines with testable transformations and maintainable integrations. |
| Data steward/quality owner | Define rules, investigate drift, inspect lineage, maintain descriptions and review changes. | Data whose meaning, quality and ownership can be explained. |
| Operations analyst/operator | Run workflows, inspect queue and run history, retry or cancel work, triage incidents. | Timely outputs and visible failure handling. |
| Business manager/report consumer | Read permitted datasets, charts, dashboards and reports; review business results. | Consistent, understandable information with provenance. |
| Project administrator/approver | Manage membership, project lifecycle and governed changes. | Appropriate access and reviewed change application. |
| Platform administrator | Onboard/offboard people; manage organisations; operate identity and platform configuration. | Controlled tenant lifecycle and safe administration. |
| Security/audit reviewer | Review access, policy behaviour, mutation history and export evidence. | Evidence of who could access or change data and what happened. |
| Integration developer | Use scoped API tokens, REST endpoints and connector extension patterns. | Automation that obeys the same access and capability constraints as the UI. |

## Responsibility model
Each production dataset should have a business owner who signs off meaning and quality thresholds, a technical owner responsible for its recipe and connections, and an operator responsible for delivery and failures. These may be the same person in a small team. The platform administrator should not automatically be treated as the business approver of every metric.

The proposed sponsor is accountable for outcome measures and scope. The product owner prioritises the backlog. Data stewards approve rule and classification choices. Engineering and operations validate execution and recovery. Security approves deployment-specific controls. Named individuals and formal sign-off remain to be supplied by the adopting organisation.

<!-- PAGE -->
# Access model and scope

## Project role model
Roles are cumulative: viewer, operator, editor and admin. Organisation membership and project authorization still apply. API-token scope can restrict an otherwise privileged user. The following is a business summary; the central permission policy and service-specific safeguards remain authoritative. [S06]

| Role | Intended permissions | Important boundary |
|---|---|---|
| Viewer | Read permitted project assets and perform permitted analytical previews. | Cannot change saved definitions or membership. Row/column policies can restrict visible data. |
| Operator | Viewer access plus execution and operational actions such as runs and incident handling. | Does not gain unrestricted definition editing. |
| Editor | Create and update datasets, rules, pipelines and other project definitions. | Governed changes and external commits may require an approver. |
| Project admin/owner | Manage project access and administration; higher project privileges. | Tenant boundary and additional endpoint safeguards still apply. |
| Platform admin | Manage accounts and organisations. | Separate platform responsibility; do not infer that every cross-tenant data action is permitted. |

## Current business scope
Project workspaces; identity and membership; file ingestion and profiling; connector discovery and extraction; saved transformations; quality checks and comparisons; lineage and governance; workflows and schedules; notifications and incidents; SQL and notebooks; controlled SQL-table editing; charts, dashboards, reports, catalog and supported publishing.

## Future scope
Guided onboarding; packaged worker/scheduler operations; durable uploads; enterprise identity; deployment hardening; deeper governance; immutable dataset versions; centrally defined metrics and contracts; streaming/CDC; richer reporting and collaboration; advanced optimization; plugins, migration importers and embedded use.

## Business boundaries
No claim of arbitrary autonomous AI transformation: intelligence is deterministic and makes no model calls. No implied write-back to every source. No claim that a connector's presence means its driver, credentials and real-world verification exist. No claim that definition versioning already provides historical data snapshots. Full enterprise compliance, commercial packaging and universal performance guarantees are outside this baseline.

<!-- PAGE -->
# Primary end-to-end workflow

## UC-01: Prepare and deliver a recurring trusted dataset
**Actors:** analyst, data owner, operator and report consumer. **Trigger:** a new file arrives or an extraction becomes due. **Preconditions:** project access, authorised source credentials, required reader/driver and a defined output. **Outcome:** a traceable, checked dataset delivered through a supported destination or report.

{{WORKFLOW}}

| Step | User action and system response |
|---|---|
| 1. Establish the workspace | Create/select the project, assign members and identify the business owner and intended output. |
| 2. Add data | Upload a supported file or configure a source and extraction job. Display actual connector readiness. |
| 3. Resolve interpretation | Inspect format, schema, types, previews and inference evidence. Resolve blocking ambiguity before import. |
| 4. Prepare | Apply ordered recipe steps: clean text, retain columns, convert types, join, aggregate and calculate. Preview changes. |
| 5. Validate | Apply rules and compare against reference data or prior outputs. Quarantine error rows where configured; report warnings. |
| 6. Review and run | Save the definition; obtain approval where required. Execute the pipeline or dependency workflow and inspect outcomes. |
| 7. Deliver | Publish to an implemented target or create charts/reports. Reconcile output with business control totals. |
| 8. Operate repeatedly | Schedule work; ensure a worker/ticker is actually running; inspect history, notifications and incidents. |

## Exception paths
Ambiguous dates require a decision; unavailable drivers produce a stated refusal; invalid rules or recipes fail validation; unauthorized access is refused; failures retain run evidence; source drift is surfaced; stale write-back data prevents unsafe commit. A queued run is not successful execution. Users must distinguish preparation preview, completed materialisation and successful external delivery.

**Current limitation:** historical comparison is available, but immutable version pins and deterministic replay of the exact original state are planned under P7/Phase 18. [S01, S04, S07-S11]

<!-- PAGE -->
# Other business use cases

| ID | Use case and users | Supported outcome and boundary |
|---|---|---|
| UC-02 | Monthly reconciliation: finance/operations analyst | Import two datasets, compare rows and distributions, run saved tests, retain evidence and export findings. Not an accounting ledger. |
| UC-03 | Source-to-report refresh: analytics engineer | Extract data, transform, quality-check, publish and schedule. Background execution requires an operating worker/ticker. |
| UC-04 | Incident investigation: operator/steward | Inspect failures, freshness/volume signals, schema drift and lineage; acknowledge, assign and resolve incidents. |
| UC-05 | Governed recipe change: editor/approver | Propose, review, approve/reject and inspect versioned definitions and audit history. Data snapshot history is separate future scope. |
| UC-06 | Controlled live-table correction: editor/approver | Stage identified SQL-row edits, inspect generated statements, rehearse where supported and commit or export a migration. |
| UC-07 | Exploratory analysis: analyst/engineer | Query a configured SQL source, save queries and use notebook cells; Python execution depends on a successful sandbox probe. |
| UC-08 | Management reporting: BI analyst/manager | Create supported charts, dashboards, pivots and Excel/CSV/HTML reports. Public share viewing and richer BI UX remain planned. |
| UC-09 | Account lifecycle: administrator | Invite using activation codes, reset access, manage roles, revoke tokens and deactivate accounts; email delivery is future work. |
| UC-10 | Sensitive-data review: steward/security reviewer | Run deterministic PII analysis, inspect masking suggestions, apply supported security policies and review retention/erasure operations. |
| UC-11 | Integration automation: developer | Use scoped, revocable API tokens and the REST API to operate permitted resources. Broad public CLI/Terraform support is future work. |
| UC-12 | Historical reporting: auditor/analyst | Planned: read an earlier snapshot, compare versions, append a rollback and replay with pinned inputs and execution context. |
| UC-13 | Near-real-time operations: data engineer | Planned: consume CDC or events, track offsets, manage late data and update downstream outputs with declared delivery semantics. |
| UC-14 | Shared metric governance: analytics owner | Planned: define a metric once, expose its dimensions and version it consistently across charts, reports and queries. |

The use cases above describe business tasks rather than separate licensed modules. Each adopts the same project boundaries, truthful capability reporting and traceable execution principles.

<!-- PAGE -->
# Requirements: workspace and identity

**Priority: Must. Status: Available, with the gaps stated below.** These requirements support BO-04 and BO-06 and use cases UC-01, UC-05, UC-09 and UC-11. [S01, S02, S05, S06]

| ID | Business requirement | Acceptance evidence to require |
|---|---|---|
| BR-01 | Provide authenticated, project-scoped workspaces with project creation, rename, archive and supported deletion. | Users can locate their authorised projects; lifecycle changes preserve access constraints and disclose consequences. |
| BR-02 | Manage project members using viewer/operator/editor/admin roles. | Role changes take effect centrally; negative tests reject unauthorized reads, writes and membership changes. |
| BR-03 | Separate organisations and their members/projects. | A user in one organisation cannot gain another organisation's project data by changing an identifier. |
| BR-04 | Provide password login, own-password change and sign-out-everywhere. | Old session tokens are rejected after the user's token version changes. |
| BR-05 | Allow administrators to invite users and issue single-use reset/activation codes. | Codes expire, cannot be reused and activate the intended account only; inactive users cannot sign in normally. |
| BR-06 | Provide named, scoped, revocable API tokens for automation. | The secret is shown once; read scope cannot mutate; revoked tokens no longer authenticate. |
| BR-07 | Support display names, account administration and organisation create/rename. | Authorised changes appear in the interface and relevant audit history; last-admin protections apply. |
| BR-08 | Persist user theme and density preferences. | Light, dark and system themes and density controls behave consistently for that user. |

## User experience and current limits
The navigation exposes administration to platform administrators, uses project names in context and supplies more readable business labels. P0 links health information to system status. Initial P2 commits add the project checklist, grouped Workspace menu and simpler data-entry choices; Home mirroring, sample-workspace creation and tours remain future work. [S15]

Invitation currently means a code workflow, not an automated invitation email. Login remains password-based for ordinary users. Existing OIDC-related backend work does not constitute an end-to-end available SSO experience; OIDC, SAML and MFA remain P4 work. The P1 plan's active-session inventory and expiry display are not present in the inspected surface; sign-out-everywhere uses token versioning. Login throttling is an unevidenced optional improvement. These distinctions remain open backlog items rather than silently inheriting the phase's done label.

<!-- PAGE -->
# Requirements: connect and ingest

**Priority: Must. Status: Available/Conditional.** Supports BO-01, BO-03 and UC-01/03. [S01, S03, S07]

| ID | Business requirement | Current scope and acceptance condition |
|---|---|---|
| BR-09 | Offer a searchable connector catalogue with truthful capabilities. | 211 registered connectors; display verification tier, availability and missing dependencies rather than implying universal readiness. |
| BR-10 | Configure and test source connections; discover supported streams and read data. | Each connector performs only declared capabilities; authentication, pagination and errors retain their own limitations. |
| BR-11 | Run full-refresh and supported incremental extraction jobs. | Track outputs, watermarks and outcomes; report source/driver refusals accurately. This is batch extraction, not log-based CDC. |
| BR-12 | Analyse files before materialisation. | Detect format, encoding, separators, headers and types with evidence; block ambiguous interpretations instead of silently guessing. |
| BR-13 | Read supported tabular and nested file families. | Delimited/fixed-width, Excel, JSON/JSONL, YAML, XML, Parquet, Avro, ORC, SQL dump, SAS and Stata paths are present, subject to reader dependencies. |
| BR-14 | Preserve business meaning during ingestion. | Protect leading-zero identifiers and exact decimals; retain declared schema; report conversion uncertainty and bad values. |
| BR-15 | Persist reusable ingestion decisions and dataset metadata. | Reapply an ingestion specification by column fingerprint/name pattern; expose schema, previews, profiles and run provenance. |
| BR-16 | Support large-upload mechanics and bounded profiling. | Chunked/resumable API and streaming profiling exist; current UI wiring and durable sessions remain P2/P3 work. |
| BR-17 | Detect source schema changes. | Scheduled discovery creates/updates drift incidents; an unreachable source is skipped with a reason, not falsely reported as schema loss. |

## File and connector distinctions
The upload reader registry and connector format registry are different surfaces. The latter also includes Arrow/Feather, TOML, INI, Markdown tables and supported log formats. A format supported through a file/object connector is not automatically accepted by the upload modal. Readability and writability also differ by format.

The current connector registry reports **155 available in the inspected environment, 50 tier-2 and 161 tier-4**; available does not mean live-verified. PDF table extraction, SPSS, ODS and 7-Zip support remain unavailable or dependency-gated as documented. Source credentials and drivers must be validated for an actual deployment before adoption.

<!-- PAGE -->
# Requirements: prepare data in Studio

**Priority: Must. Status: Available/Partial.** Supports BO-01, BO-03, BO-06 and UC-01/03. [S01, S03, S08]

| ID | Business requirement | Current scope and acceptance condition |
|---|---|---|
| BR-18 | Provide an interactive tabular preparation surface. | Virtualised grid, selection, keyboard navigation, copy, resizing and column operations work on the loaded preview. |
| BR-19 | Build ordered, reusable transformation recipes. | Rename/select/drop columns; convert, filter, clean, fill, deduplicate, split, join, aggregate, reshape and derive through supported steps. |
| BR-20 | Preview transformations before running them. | Show schema and row effects; retain the last valid preview with a stale marker when a new configuration is invalid. |
| BR-21 | Offer a discoverable transformation library. | 173 named tools across 11 categories; searchable names/synonyms and type-aware context menus; examples derive from the registry. |
| BR-22 | Support formula-based derived columns. | Spreadsheet-style formulas compile to the shared expression model; actionable syntax/type errors identify unsupported requests. |
| BR-23 | Show column profiles and preparation effects. | Null/quality summaries and distributions are labelled with sampling limits; a preview statistic must not imply a full-dataset scan. |
| BR-24 | Name, save, edit and run pipelines to produce derived datasets. | Save-time naming and inline list rename exist; persist recipe/run relationships. Preview success is not completed execution. |
| BR-25 | Make execution location explainable. | The plan explains which operations could run in a source and why others remain local; actual run pushdown is still deferred. |

## Library coverage
Current categories are Text (43), Date & time (33), Numeric (23), Cleansing (15), Encoding & privacy (14), Type & conversion (10), Validation (9), Columns (7), Rows (7), Missing data (6) and Nested data (6). The appendix names every current tool. Base transformation steps and formula names are separate inventories, so their counts must not be added into a marketing total.

The expression registry contains 186 functions; the formula parser exposes 207 accepted names including aliases. Older prose's 87 figure describes an earlier milestone, not the current parser surface. Function count does not imply Excel parity.

Studio preparation edits a recipe. Direct cell editing of a live SQL table belongs to the separate Table editor. Paste-as-new-dataset, richer recipe management, advanced analytic families and formula-editor completion remain unfinished. [S08]

<!-- PAGE -->
# Requirements: quality and intelligence

**Priority: Must for quality; Should for assisted analysis. Status: Available.** Supports BO-03/04 and UC-02/04/10. [S09]

| ID | Business requirement | Current scope and acceptance condition |
|---|---|---|
| BR-26 | Define and maintain reusable quality rules. | Not-null, uniqueness, allowed values, numeric range, pattern, custom expression, row count and freshness rules are exposed. |
| BR-27 | Separate warnings from failing-data handling. | Warning rules report; error-level handling can quarantine failed rows. Results identify rules and row/dataset-level failures. |
| BR-28 | Compare datasets and pipeline-run outputs. | Show supported schema/row changes and comparison results; do not label this immutable version history. |
| BR-29 | Save and rerun statistical tests. | Testing Lab includes Welch t-test, two-proportion z-test and chi-square distribution test with persisted definitions/results. |
| BR-30 | Detect and review schema drift. | Present changed columns/types and drift events; authorised users acknowledge relevant changes. |
| BR-31 | Derive dataset and column lineage and downstream impact. | Explain origins and dependencies from recipe structure; transformation changes alter derived lineage consistently. |
| BR-32 | Assist with sensitive data, relationships and duplicates. | Deterministic PII detection, masking suggestions, join-key suggestions and entity-resolution analysis disclose methods. |
| BR-33 | Help explain and document data. | Deterministic description-to-steps, metric-change explanation, draft documentation and rule suggestions remain evidence-based and bounded. |

## Business rules for trustworthy results
Missing is not zero. Nullable comparisons preserve unknown values until the defined filtering/conditional boundary. Summing an entirely missing group yields missing. A dialect that cannot express an operation refuses it instead of approximating. Suggestions disclose method and applicable confidence/evidence; they do not automatically become business-approved rules.

Rule configuration is owned by the business/data steward: the software cannot decide that a revenue total is correct simply because it is numeric. Acceptance must include representative valid records, known defects and boundary cases agreed by the owner.

## Limits
Statistical tests already present in Testing Lab are distinct from the future broad statistical/ML transformation family. Entity-resolution analysis already exists, while a complete fuzzy-join/survivorship tool workflow is still planned. Streaming profiling does not calculate full duplicate-row detection; it reports that measure as unavailable. No model calls are used by service-intelligence.

<!-- PAGE -->
# Requirements: workflows and operations

**Priority: Must. Status: Available/Partial.** Supports BO-05/07 and UC-01/03/04. [S01, S02, S10]

| ID | Business requirement | Current scope and acceptance condition |
|---|---|---|
| BR-34 | Coordinate multi-step data workflows. | Build and validate dependency graphs linking extraction, transformation, quality, publishing and other supported node handlers. |
| BR-35 | Queue and execute workflow runs. | Track states, dependencies, outcomes and cancellation; configured retries and failure paths remain inspectable. |
| BR-36 | Schedule recurring work. | Cron schedules, common presets, enable/disable and trigger-now are present; the scheduler must actually be invoked. |
| BR-37 | Support dated backfills and runtime parameters. | Preview/run backfills and use documented date/parameter macros; do not confuse these macros with future Studio recipe templates. |
| BR-38 | Preserve execution history and operational comparison. | Inspect pipeline/workflow runs, audit information and supported run differences; distinguish queued, running, failed and completed work. |
| BR-39 | Raise and handle incidents and notifications. | Observe quality/freshness/volume/drift signals; inspect, assign, acknowledge and resolve incidents; configure notification targets. |
| BR-40 | Expose accurate runtime and system health. | Liveness/readiness, service status, queue/due counters, stalled-work hints and metrics tell operators when attention is required. |
| BR-41 | Provide evidence for deployment and recovery. | Setup, smoke, verification, backup/restore tooling and deployment documentation exist; record actual execution for the target installation. |

## Important operating distinction
Workflow and schedule engines are implemented, but starting the web and API processes alone does not establish that recurring work is being consumed. P0 warns when queued/due work appears stalled. P3 will package supervised workers and the schedule ticker and add direct runtime heartbeats.

The P0 stalled heuristic uses queued/due work, absence of running work and an oldest waiter beyond 15 minutes. P3 aims to detect worker loss within one minute using heartbeats, and create queue-age incidents after 30 minutes. The latter are future requirements, not current guarantees.

Notification facilities exist; default failure/critical-incident routing, guided target setup and richer delivery UX remain planned. Delivery to external systems depends on their configuration and availability. A database-backed lease scheduler is not a blanket claim of distributed exactly-once processing.

<!-- PAGE -->
# Requirements: governance and enterprise

**Priority: Must for controlled deployments. Status: Available/Partial.** Supports BO-03/04/06 and UC-05/09/10. [S06, S11]

| ID | Business requirement | Current scope and acceptance condition |
|---|---|---|
| BR-42 | Version governed definitions. | Keep versions of supported pipeline/workflow definitions, compare changes and restore a definition where permitted. |
| BR-43 | Review changes before application in governed projects. | Change requests support submission, approval/rejection and withdrawal; direct edits/commits respect central review rules. |
| BR-44 | Maintain a project-level audit trail. | Record actor, action, path/outcome and time for covered mutations; expose project audit views without logging request bodies. |
| BR-45 | Support resource discussion and promotion. | Discussion/comment primitives and supported cross-project promotion exist; comprehensive in-context comments remain planned. |
| BR-46 | Apply row and column security policies. | Evaluate policies consistently through supported access paths and allow policy preview; test restricted and unrestricted personas. |
| BR-47 | Manage retention, erasure and usage. | Expose supported retention/erasure operations and organisation/project usage controls with explicit outcomes. |
| BR-48 | Maintain discoverability and business metadata. | Search catalogued datasets; annotation/glossary APIs support descriptions, ownership/certification and terms; richer editing UX is planned. |
| BR-49 | Protect administrative lifecycle and credentials. | Prevent accidental loss of the last active platform admin; encrypt stored connection secrets and revoke access through supported lifecycle actions. |

## Critical distinction: definitions versus data
Definition history answers which recipe was saved. Dataset snapshots answer which exact data was read or produced. Pipewright has the former; universal immutable data versioning is accepted future work. Current dataset lineage and run history do not by themselves guarantee six-month historical replay.

## Erasure boundary
Current erasure functionality cannot be presented as the future immutable-history lifecycle. The accepted Phase 18 requirements identify an existing in-place artifact rewrite and require a new design that distinguishes ordinary corrections from destructive historical erasure, prevents historical recovery of erased data and reports incomplete outcomes honestly. P6/P7 own that work.

No compliance certification or legal sufficiency is claimed. The adopting organisation must define the applicable records, policies and approval responsibilities; this document specifies product behaviour and evidence, not legal advice or a regulatory opinion.

<!-- PAGE -->
# Requirements: reporting and delivery

**Priority: Must for delivery; Should for richer consumption. Status: Available/Partial/Conditional.** Supports BO-03/07 and UC-01/08. [S12]

| ID | Business requirement | Current scope and acceptance condition |
|---|---|---|
| BR-50 | Create charts from authorised datasets. | Bar, column, line, area, scatter, pie, KPI and table types are declared; validate required dimensions/measures and category limits. |
| BR-51 | Compose project dashboards and pivots. | Save dashboards using supported tiles/filters and compute pivots; richer drag/resize, refresh and comparison indicators are future work. |
| BR-52 | Generate downloadable reports. | Dataset/chart/dashboard report paths support Excel, CSV and HTML as applicable; show generation/delivery history. |
| BR-53 | Export audit evidence. | Dataset/run audit exports are HTML. This externally prepared BRD PDF does not add native PDF export to the application. |
| BR-54 | Configure and test destinations. | PostgreSQL, S3 and local-export configuration/test paths exist; supported write capability must be distinguished from dataset-publish routing. |
| BR-55 | Publish datasets to PostgreSQL. | Append/replace flow validates configuration and records the actual outcome; business acceptance reconciles target contents. |
| BR-56 | Connect to and publish through BI services. | Power BI and Tableau first-path connection, metadata and publishing flows exist; real service credentials and permissions are prerequisites. |
| BR-57 | Share consumption safely. | Authenticated project consumption is available; public token-viewer routing and usable share links are planned under P3. |

## Delivery limits that matter to buyers
The existence of an S3 or local-export connector and a successful connection test do not mean the main dataset-publish endpoint implements those destinations. Current documented dataset publication is PostgreSQL; additional low-level connector write paths must be evaluated separately.

Dashboard share-token creation/revocation exists in the backend, but the inspected UI explicitly avoids offering a public viewing link because the public viewer route is absent. P3 completes or removes that incomplete capability. P8 expands dashboard UX, contextual comments, report delivery to Slack and PDF/print output.

Power BI and Tableau support is publishing-oriented. It is not a complete external BI administration, workbook lifecycle or semantic-model governance product. External vendor changes and target-side authorization are deployment validation responsibilities.

<!-- PAGE -->
# Requirements: advanced analyst work

**Priority: Should; Must where the use case requires it. Status: Available/Conditional.** Supports UC-06/07/11. [S13]

| ID | Business requirement | Current scope and acceptance condition |
|---|---|---|
| BR-58 | Provide a SQL workbench. | Run multi-statement scripts against configured sources with a schema browser, saved queries, history, EXPLAIN and cursor-aware completion. |
| BR-59 | Make SQL execution mode explicit. | Read-only is the default; write mode requires the proper privilege and supported restrictions/timeouts are reported. |
| BR-60 | Offer notebooks with shared data frames. | SQL, recipe and sandboxed Python cells can cooperate through supported tabular state, subject to environment capability. |
| BR-61 | Expose recipes as code. | Export/import supported YAML recipes without losing supported recipe meaning; suitable for review and automation. |
| BR-62 | Stage edits to a live SQL table. | Resolve trustworthy row identity before editing; support set cell, insert/delete row, add/drop/rename column. |
| BR-63 | Preview the consequences of write-back. | Validate a whole change set, show SQL and affected-row scope, rehearse supported operations and disclose skipped DDL checks. |
| BR-64 | Detect concurrent changes and govern commit. | Compare recorded cell values, stop conflicting commits, apply transaction limits and require review where configured. |
| BR-65 | Support review without direct execution. | Export a migration/statement representation when teams prefer an external database review process. |

## Environment limits
Python notebook execution is disabled on macOS when the memory-isolation probe fails. Linux execution also depends on the probe and supported resource controls. This is an explicit refusal, not a silently weakened sandbox. Notebook execution is bounded in the request: 15 seconds per Python cell and 120 seconds for the notebook, with SQL timeout behaviour per dialect.

SQL write-back is implemented with dialect-aware paths; the handoff records live execution evidence only against SQLite. PostgreSQL/MySQL write-back still needs its own live acceptance evidence, even though PostgreSQL is used by the application itself. Rehearsal skips structure changes on non-transactional-DDL paths and reports them.

File/SaaS/object-store/NoSQL write-back, column retyping, primary-key/index/constraint changes, three-way conflict resolution and grouped savepoints are not delivered. Advanced notebooks are not unrestricted shell execution or a hosted machine-learning platform.

<!-- PAGE -->
# Data and integration requirements

## Business information model
| Information object | Business meaning and relationship |
|---|---|
| Organisation, user and project | Tenant boundary, actor and owned workspace; memberships determine project access. |
| Connection and secret reference | How an authorised external source/target is reached; secrets must not appear in ordinary metadata views. |
| Dataset and ingestion specification | Materialised data with schema/profile/provenance and recorded decisions about how the source was interpreted. |
| Pipeline and workflow | Ordered preparation recipe, and a graph coordinating dependent operations across that recipe and other actions. |
| Run, schedule and incident | An execution attempt, its recurrence definition and an operational/quality issue needing attention. |
| Quality rule and saved test | Assertions and comparison definitions that express expectations about business data. |
| Definition version and change request | Reviewable history of supported definitions and the approval lifecycle for proposed changes. |
| Chart, dashboard, report and glossary term | Consumption assets and shared business descriptions; central metric definitions are future scope. |
| Change set | Staged, identified edits proposed for a live SQL table, with validation and commit evidence. |
| Dataset version and execution pins | Planned immutable data history and exact run inputs/outputs, distinct from today's dataset records. |

## Integration boundaries
Inputs include files, relational systems, object stores, supported API protocols and vendor connectors. Outputs include derived datasets, reports, supported database publication and BI publishing. Public REST/OpenAPI and scoped tokens provide automation access. Connector SDK/conformance machinery exists, but the broad plugin ecosystem and product-wide CLI/Terraform ambitions are future scope.

## Data handling rules
- Canonical types must preserve decimals, identifiers, nulls, nested values and timestamp meaning; lossy conversions must be explicit.
- Data preview and profiling must show sampling/truncation so consumers know what was evaluated.
- Run metadata must distinguish source input, transformation result, quarantine output and publish outcome.
- Current file-backed artifacts and PostgreSQL metadata must both be covered by backup and recovery.
- Secret resolution, tenant/project authorization and capability checks must apply equally through UI and API workflows.

The implementation uses a web frontend, a modular API gateway/services layer, PostgreSQL metadata and stored artifacts. This BRD specifies business behaviour, not a requirement to split every service package into an independently deployed microservice. [S01, S06-S13]

<!-- PAGE -->
# Non-functional requirements

These requirements are business acceptance conditions. Current mechanisms are distinguished from proposed deployment targets; the repository does not establish a production SLA, scale benchmark or accessibility certification.

| ID | Requirement | Current evidence / remaining acceptance |
|---|---|---|
| NFR-01 | Correctness and data fidelity: do not silently change business meaning. | Canonical types, explicit null semantics, differential tests and refusals exist. Validate each deployment's critical calculations and dialects. |
| NFR-02 | Access control: every protected path must enforce tenant/project rules. | Central permission policy, role hierarchy and token scope exist. Exercise negative tests for the actual user/tenant model. |
| NFR-03 | Secret protection: do not expose credential values in routine UI, logs or exports. | Encrypted connection secrets, hashed passwords/codes/tokens and secret references exist; key custody/rotation remains an operator responsibility. |
| NFR-04 | Reliability: show real state and recover from process failure without misleading success. | Run states, leases and stalled hints exist. Supervision, direct heartbeats and durable upload recovery are P3 work. |
| NFR-05 | Performance: keep previews interactive and execution bounded. | Virtualised grid, bounded notebook execution and sampling exist. P5 must measure hot-endpoint performance; P9/22 improves execution. |
| NFR-06 | Recoverability: restore metadata and artifacts together. | Backup and restore-drill tooling exists. Agree RPO/RTO and demonstrate them with representative data before production. |
| NFR-07 | Usability: business users can interpret types, failures and next actions. | Labels, themes, project checklist and pipeline naming exist. P2's independent sub-20-minute workflow remains an adoption target. |
| NFR-08 | Observability: correlate requests and operational outcomes. | Request identifiers, health endpoints, metrics and audit history exist. P3/P5 add direct runtime health and operating guidance. |
| NFR-09 | Maintainability: new capabilities must obey shared contracts. | Registered service hooks, connector conformance and generated tool documentation exist; broad plugin compatibility is Phase 23. |
| NFR-10 | Honest degradation: unavailable features must be labelled or refused. | Verification tiers, driver gating, unsupported dialect errors and sandbox checks are existing design rules. |

## Targets to agree before a production rollout
Define supported concurrent users, data sizes, completion windows, p95 response times, storage retention, availability, RPO/RTO and browser/accessibility coverage. Proposed acceptance should include keyboard-only critical journeys, accessible error messages and readable chart alternatives. Do not publish numeric performance or compliance claims until those workloads and controls have actually been tested.

<!-- PAGE -->
# Current limitations and readiness

| Area | Actual boundary at this baseline | Business consequence |
|---|---|---|
| Connector assurance | 50 tier-2, 161 tier-4; no tier-1/tier-3 registry entries. 155 currently report available. | Pilot each required connection; documentation-based capability is not vendor-live verification. |
| Optional engines/drivers | Nine declared engines are unavailable; warehouse connectors are often driver-gated. | Catalogue coverage is broader than this installation's operational coverage. |
| Enterprise identity | End-to-end SSO/MFA not delivered; OIDC-related code lacks recorded live IdP validation. | P4 or an explicitly accepted alternative is an enterprise adoption gate. |
| Background work | Worker/ticker mechanisms exist, but packaged supervision is not shipped. | A visible queued run can remain unprocessed unless operators run the necessary components. |
| Upload durability | Chunk sessions are process-local; UI does not yet use the complete resumable flow. | Restart/multi-process operation needs care; P2/P3 complete the experience. |
| Historical reproducibility | Lineage and definition versions exist; immutable dataset snapshots do not. | Past data cannot yet be addressed or replayed with Phase 18 guarantees. |
| Source-side execution | Planner/compiler/executor machinery exists; extraction-run integration is deferred. | Advisory plans must not be presented as realised performance savings. |
| Reporting/share | Native PDF export and public dashboard viewer are absent. | Use available exports/authenticated access; P3/P8 complete the remaining paths. |
| Notebook/write-back | Python is disabled on the current macOS sandbox; SQL write-back has limited recorded live evidence. | Verify the target environment before committing to those workflows. |
| Tool depth | 173 current tools, not the roadmap's approximately 420 ambition. | Advanced windows, ML/statistics, geospatial and recipe-management workflows still need development. |

## Evidence interpretation
The handoff records 6,038 Python tests (573 skipped) and 678 web tests; the latest P2 commit records 6,041 Python passes, 573 skips and 678 web passes with zero warnings. Those are historical results, not proof that all integration infrastructure ran or a fresh live test of every feature for this BRD. Container-backed tests can skip locally; CI has separate real-server prerequisites. [S15]

Older feature-guide and roadmap statements conflict with newer code in places. The reconciliation register near the end records those differences and the chosen interpretation. [S01-S05]

<!-- PAGE -->
# Roadmap coverage and delivery map

Two planning views overlap: the product roadmap describes capability depth; the newer production-readiness plan describes adoption and operational sequencing. They are not two independent sets of delivered features. No calendar delivery dates are approved in this BRD. [S02-S04]

| Production phase | Status | Business outcome / related product phase |
|---|---|---|
| P0 - Truth and trust | Done | Clear language/navigation and honest visibility into stalled background work. |
| P1 - Identity core | Done with noted residuals | Account lifecycle, password/session invalidation and scoped API tokens; remaining plan/code deltas are listed here. |
| P2 - Guided first win | Partial; in progress | Project checklist, initial type consistency and naming delivered; sample project, Home mirroring, tours and resumable UI remain. |
| P3 - Operational backbone | Planned | Supervised workers/ticker, heartbeats, durable uploads, public dashboard viewer and cross-project operator views. |
| P4 - Enterprise identity | Planned | Live OIDC integration, SAML and TOTP MFA. |
| P5 - Deployability and scale | Planned | Production packaging, Helm, operations evidence and performance baseline. |
| P6 - Governance depth | Planned | Audit Center, policy simulation, review UX and erasure lifecycle. |
| P7 - Time travel | Planned; accepted requirements | Product Phase 18: immutable data history, temporal queries, rollback and deterministic replay. |
| P8 - BI and collaboration | Planned | Dashboard UX, contextual comments, email invitations and reporting/delivery improvements. |
| P9 - Deeper execution | Planned | Pushdown/IR cutovers; initial CDC and semantic layer; optimization groundwork. |

## Remaining product roadmap beyond the above
Phase 16 remains partial and requires additional transformation families. Phase 19 covers semantic metrics and data contracts. Phase 20 covers broader CDC and event processing. Phase 21 covers live multi-user Studio collaboration. Phase 22 covers cost-based optimization and resource governance. Phase 23 covers ecosystem extensibility. P9's initial increments do not automatically complete Phases 19, 20 or 22.

The original phases 08-15 and 17 are recorded as done, but their explicit exclusions remain backlog or deliberate boundaries. Optional "push further" items and the seven speculative bets are listed separately so they are not mistaken for release commitments.

<!-- PAGE -->
# Planned: onboarding and operations

## P2 - Guided first win (Should; partially delivered)
- **PL-01 - Partial:** The project checklist now tracks Add data, Shape it, Guard it and Schedule it, supports dismissal and hides when complete. The grouped Workspace menu exists. Mirroring this state on Home remains planned.
- **PL-02 - Partial:** Add data versus Connect a source is clarified and manual registration is under advanced controls. A deletable sample workspace with orders, pipeline, rule, schedule and chart/dashboard remains planned.
- **PL-03 - Partial:** Save-time pipeline naming and inline rename are implemented. First-project, Data Quality and Schedules tours remain planned.
- **PL-04 - Partial:** Canonical type metadata and consistent dataset/Studio display, with ingestion/preview tests, are implemented. Complete upload-to-publish acceptance remains part of P2.
- **PL-05:** Wire the resumable/chunked API into upload UI with progress, retry/resume and a truthful configured limit; remove the UI's 25 MB soft cap only within backend limits.
- **Candidates:** Inline "Explain this step" help from registry documentation and purpose-specific empty-state illustrations.

**Exit condition remains open:** three non-technical testers independently build a scheduled, validated pipeline in under 20 minutes. Include interruption/retry and ambiguity. Partial delivery is established by three P2 commits; the phase is not declared complete. [S02 P2, S15]

## P3 - Operational backbone (Must for unattended use)
- **PL-06:** Package worker and schedule-ticker processes with the API in development and deployment profiles; supervise and restart them. Persist component heartbeats and show host, last activity and queue depth in System status/Home.
- **PL-07:** Open incidents for work stalled beyond 30 minutes and auto-resolve on drain. Deliver run-failure/critical-incident notifications in-app by default; guide setup of email/Slack targets.
- **PL-08:** Complete read-only public dashboard token viewing with immediate revocation and no indexing, plus a share-link UI. The plan's explicit alternative is to remove token sharing if public access is rejected at implementation time.
- **PL-09:** Replace redirect-only global runs/datasets entry points with actual authorised cross-project operator views and search/filtering.
- **PL-10:** Persist upload sessions and chunks durably so restarts do not orphan active uploads.
- **Candidate:** Dead-letter view and rerun controls for failed workflow nodes.

**Exit condition:** stop the worker during a workflow; the UI detects it within one minute and the system demonstrates safe recovery. Public tokens must never expose another project's data. [S02 P3]

<!-- PAGE -->
# Planned: identity and deployment

## P4 - Enterprise identity (Must where required by the customer)
- **PL-11: OIDC SSO.** Complete discovery, PKCE, just-in-time provisioning with a default role, optional group-to-role mapping and a configured "Continue with SSO" path. Verify against a real identity provider.
- **PL-12: MFA.** Add TOTP enrolment/QR, challenge verification, recovery codes and authorised administrator reset.
- **PL-13: SAML.** Implement signature-verified assertions using the required library and test Okta/Entra profiles; retain refusal rather than accept unsigned assertions.
- **Candidates:** A documented SCIM-lite deactivate-on-absence synchronization design, implementation if feasible, and per-organisation session/expiry policy.

**P1 residuals:** reconcile the originally planned active-session list and expiry display with the delivered token-version invalidation model. Login rate limiting remains an optional planned improvement without inspected implementation evidence. Password hashing follows current scrypt code/security documentation; the old P1 planning reference to bcrypt is not the implemented contract. [S02 P1/P4, S05-S06]

## P5 - Deployability and scale (Must for managed production operation)
- **PL-14:** Provide production packaging covering gateway, worker, web, PostgreSQL and proxy/TLS guidance; extend existing Compose assets to the complete operating model.
- **PL-15:** Provide a Helm chart with image/environment/resource values and autoscaling guidance; publish application images from tagged CI releases.
- **PL-16:** Publish operations guidance for upgrades, restore drills, scaling, scheduler identities and sizing. Demonstrate the existing backup tool's real restore path.
- **PL-17:** Measure ten hot endpoints with a reproducible load script and record environment/workload/results. A CI regression-budget job is optional until practical limits are established.
- **PL-18:** Make request correlation consistent, document Prometheus metrics and provide a slow-query logging option.
- **Candidates:** Software bill of materials and dependency-audit checks in CI.

## Acceptance principle
Deployment documentation is complete only when an operator unfamiliar with the development session can start, stop, upgrade, monitor and restore the chosen environment using it. Agree scale, availability and recovery objectives before testing. Helm files or a successful image build alone are not evidence that those objectives have been met.

<!-- PAGE -->
# Planned: governance and consumption

## P6 - Governance depth
- **PL-19 (Must):** A real cross-project Audit Center with authorised filtering, CSV/JSON export and retention settings; include covered administrative actions.
- **PL-20 (Must):** "View as role/user" simulation for row/column security on datasets, extending the existing policy-preview capability.
- **PL-21 (Should):** Reviewable diffs for definition changes and request-changes-with-comment UX on the existing approval/discussion foundation.
- **PL-22 (Must):** Distinguish ordinary data correction from destructive historical erasure, with explicit complete/failed/incomplete outcomes consistent with the accepted versioning requirements.
- **PL-23 (Should):** Catalog ownership/certification editing and glossary links from dataset pages. Candidate: PII-suggested classification tags connected to catalog and policies.

## P8 - BI and collaboration
- **PL-24 (Should):** Dashboard builder with drag/resize layout, global filters, text tiles and auto-refresh. Extend chart UX with donut and richer big-number deltas and refine existing pie/table/KPI capabilities; those existing types are not wholly new features.
- **PL-25 (Should):** In-context comments on datasets, pipelines and dashboards, with mentions generating notifications. This extends an existing discussion API; it does not yet mean simultaneous Studio editing.
- **PL-26 (Should):** Send invitations by email through configured SMTP/templates, building on P1's delivered activation-code mechanism.
- **PL-27 (Should):** Add native PDF report generation through a maintained print path, or explicitly provide well-designed print CSS and a Print to PDF action if native generation is not adopted.
- **PL-28 (Should):** Deliver scheduled reports to a configured Slack target.
- **Candidate:** Dashboard/report subscriptions such as a weekly email.

## Acceptance examples
A steward sees a clear change diff before approval; a viewer cannot escalate through a policy-preview route; a revoked public share is immediately inaccessible; mentions reach only authorised users; printed reports paginate correctly; report delivery failures retain a visible outcome. Erasure must not silently leave reachable historical bytes while reporting success.

Catalog APIs, project audit history, definitions, discussion primitives, charts and report generation already exist. The planned work deepens and connects those paths. [S02 P6/P8, S04, S11-S12]

<!-- PAGE -->
# Planned: time travel and reproducibility

**PL-29 | Product Phase 18 / P7 | Must for historical reproducibility | Status: accepted future requirements, not implemented.** [S04]

## Business capabilities
Store an append-only series of immutable dataset snapshots; address a stored dataset at a time/version; compare any two versions; roll back a bad load by appending a new version; pin the exact input and output of a run; reproduce historical results using recorded execution context. Retention governs availability without corrupting active references.

## Mandatory business rules
- **Universal coverage:** inventory uploads, extraction, transformations and quarantine producers, plus every preview, report, comparison, export and publish consumer. Specify logical dataset identity and input/output version behaviour for each.
- **Atomic publication:** dataset head, version and run provenance must be consistent. Define full-refresh/incremental extraction and watermark interaction; do not publish partial success.
- **Temporal reads:** AS OF applies to materialised Pipewright datasets. It must not rewrite SQL sent to external customer databases.
- **Truthful diffs:** classify changed rows/cells only with trustworthy unique identity. Otherwise provide duplicate-aware added/removed results and explain the unavailable classification; handle schema changes explicitly.
- **Append-only rollback:** do not overwrite, delete or renumber history, and do not rerun the source pipeline to claim rollback.
- **Deterministic replay:** record evaluation instant, timezone, runtime/semantic version and supported nondeterministic inputs. Reuse that context for time-dependent functions; report incompatible replay explicitly.
- **Historical security:** apply the intended current authorization and row/column policy to historical access. Define viewer/operator/editor/admin handling centrally.
- **Erasure:** distinguish correction from destructive removal across historical artifacts. Do not allow replay to resurrect erased data; disclose unavailable or incomplete outcomes.
- **Safe retention:** protect active reads, publication and durable pins from garbage collection with an enforceable concurrent protocol; test crashes, retry and resumed sweeps.
- **Controlled migration:** separate schema migration from idempotent artifact backfill. Preserve canonical types and define old artifact-field compatibility.

## Acceptance and delivery
Increment through storage, publication/backfill, temporal reads, diff/rollback and replay. Test decimals, timestamps, nulls, nested data, duplicate keys, cursor/order stability, unavailable/pruned/erased versions, limits and interruption. Run the authenticated end-to-end version/query/diff/rollback/replay flow against the actual checkout. A preserved unfinished branch is reference material and must not be counted as delivered capability.

<!-- PAGE -->
# Planned: shared meaning and live data

## PL-30 - Semantic layer and data contracts
**Product Phase 19; P9 initial semantic work. Priority: Should, or Must for shared enterprise metrics.** [S03]

Define metrics and dimensions once with owner, description, expression, filters, validity and version history. Charts, reports, pivots and exports resolve consistent definitions. Show impact before changing a definition. An "active customer" should not be independently redefined by every dashboard.

Publish producer/consumer data contracts covering schema, types, nullability, freshness, allowed values and expected volume. Consumers subscribe; breaking changes are blocked at the pipeline boundary rather than merely reported after downstream damage. This extends current quality/drift capabilities into an explicit two-sided agreement.

**Acceptance:** two consumers resolve the same versioned definition; changes identify impacted consumers; deliberately broken contract fixtures fail before publication. The semantic roadmap depends on canonical execution foundations and time-travel capability. Current glossary terms and chart-local measures do not satisfy this requirement.

## PL-31 - Streaming and change data capture
**Product Phase 20; P9 starts with PostgreSQL CDC and inbound webhooks. Priority: Should where freshness demands it.** [S02-S03]

Read source change logs: PostgreSQL logical replication, MySQL binlog, MongoDB change streams and SQL Server CDC. Take an initial snapshot, then apply inserts, updates and deletes with resumable positions. Expand event ingestion to Kafka/Confluent/Redpanda, Kinesis, Pub/Sub, Event Hubs, Pulsar, RabbitMQ, NATS, MQTT, SQS, Debezium and inbound webhooks as scoped by source capability.

Support tumbling, hopping, sliding and session windows; watermarks and late arrivals; stateful aggregation/checkpointing; stream-table joins. Start with micro-batches; continuous execution is justified only by an actual latency requirement.

**Delivery semantics:** exactly-once only where the sink supports it; otherwise state at-least-once and duplicate risk. Offset recovery, duplicate handling, checkpoint restart, delete events and late-arrival behaviour require acceptance tests.

Current scheduled incremental extraction is not log-based CDC. The 13 deferred streaming/queue/CDC catalogue entries are not part of the 211 current connector registry. Inbound webhook ingestion is separate from existing outbound notification webhooks. gRPC remains a separate connector gap, not automatically delivered by CDC.

<!-- PAGE -->
# Planned: collaboration and optimization

## PL-32 - Real-time collaboration
**Product Phase 21. Priority: Should.** [S03]

Allow several analysts to work on one Studio recipe without overwriting each other. The roadmap proposes conflict-aware shared recipe editing using a sequence CRDT, per-field last-writer-wins configuration, user presence and live cursors. Add resolvable cell-level comment threads, mentions, a dataset change feed and suggestion mode so viewers can propose steps for editors to accept or reject.

Studio productivity also needs coherent undo/redo, step duplication/disabling/reordering, reusable macros/templates, parameterisation, recipe branches/merge/comparison, step comments and replay on a new file. Some existing step actions, workflow macros and YAML import/export overlap, but the unified recipe-management experience is not delivered.

**Acceptance:** concurrent edits converge, suggestions cannot bypass role/approval rules, unauthorized users do not receive presence/data events, and comments reference the intended asset/cell. P8 comments are an earlier increment, not completion of Phase 21.

## PL-33 - Cost-based optimization and resource governance
**Product Phase 22; P9 groundwork. Priority: Should, becoming Must at agreed scale.** [S03]

Collect row counts, distinct counts, histograms and null fractions for selectivity estimates. Apply justified predicate/projection/limit optimizations, join reordering, constant folding, common-subexpression elimination and redundant-sort removal. Support federated queries across sources with deliberate data movement decisions.

Cache content-addressed intermediate results; recompute only changed partitions; adapt execution when actual join cardinality differs substantially from estimates. Add project concurrency limits, priority queues and a hard per-run memory ceiling.

**Acceptance:** optimized and unoptimized outputs remain equivalent, policy boundaries survive data movement, cached results do not cross tenants or outlive required invalidation, and workload/resource limits are measured rather than assumed.

## PL-34 - Complete existing execution machinery
P9 explicitly schedules two separately gated changes: wire the existing pushdown executor into real extraction runs, and cut over from the current dual-executor arrangement to IR-only execution. Neither change is implied by Phase 12's done label. Accepted Phase 18 scope excludes making these cutovers incidentally; P9 is the deliberate future decision point. Correctness/differential suites remain a release condition.

<!-- PAGE -->
# Planned: ecosystem and future bets

## PL-35 - Extensibility and ecosystem
**Product Phase 23. Priority: Could/Should by adoption need.** [S03]

| Capability | Remaining business scope |
|---|---|
| Plugin SDK | Versioned, capability-declared interfaces for custom connectors, steps, formula functions and charts, with first-party conformance standards. Connector-specific extension machinery already exists. |
| Public automation | Broader supported REST/CLI experience, including workflow execution from CI; Terraform provider. OpenAPI and scoped API tokens already exist. |
| Migration importers | Import dbt projects, Airflow DAGs, Alteryx workflows, Informatica mappings, SSIS packages, Talend jobs and Power Query M; show what converted and what did not. |
| Marketplace | Community connectors, industry recipe templates and shared metrics carrying honest verification status. |
| Embedded mode | Embeddable, white-labelled Studio for other software products, with explicit security and tenancy boundaries. |

## Candidate register - unscheduled exploration
These seven ideas are explicitly beyond the scheduled roadmap, not accepted release promises.

| ID | Candidate | Intended value |
|---|---|---|
| EX-01 | Browser-local sampled execution with DuckDB-WASM | Faster interactive previews; full runs remain server-side. |
| EX-02 | Numerical what-if simulation over lineage | Show which downstream reports change, and by how much, before applying a recipe change. |
| EX-03 | Assisted schema-drift repair | Propose a patch, show impact and apply only after approval. |
| EX-04 | Generated compliance evidence | Produce inventories, PII-flow maps, retention/access evidence and records for review; no implied legal certification. |
| EX-05 | Data-mesh support | Domain ownership, published contracts, federated catalog and cross-domain discovery. |
| EX-06 | Natural language over governed semantics | Resolve questions to defined metrics with visible definitions; a future design requiring explicit decisions, not an existing model capability. |
| EX-07 | Continuous data testing | Per-load suites, coverage visibility and red/green history across datasets. Existing quality tests form a partial foundation. |

The product runtime's current no-model-call rule remains authoritative. A speculative natural-language idea is not authorization to introduce model calls or change that architecture in another phase.

<!-- PAGE -->
# Backlog: advanced preparation tools

**PL-36 | Phase 16 expansion | Priority: Should by validated use case | Status: Partial.** Approximately 420 tools is the original breadth ambition, not the current count or a binding estimate. The 173 delivered tools and base steps cover common preparation; the families below remain missing or incomplete. [S03, S08]

| Family | Documented remaining ambition |
|---|---|
| Window and analytic | Row number, rank/dense rank/percent rank, ntile, lag/lead, first/last/nth value, cumulative sum/product/min/max, moving sum/average/min/max, exponential moving average, rolling deviation/correlation and session windows. |
| Statistical analysis | Describe/correlation/covariance matrices, frequency/cross-tabulation, multiple outlier methods, normality and paired/nonparametric tests, ANOVA, regression/residual analysis, confidence/sample-size tools, seasonal decomposition, autocorrelation, trend/change-point detection and distribution fitting. Existing Testing Lab tests are separate. |
| Applied statistics and ML | K-means/hierarchical/DBSCAN clustering, PCA, anomaly scoring, ARIMA/exponential/Prophet-style forecasting, KNN/iterative imputation, simple classifiers, feature importance, one-hot/ordinal/target encoding, TF-IDF and similarity matrices. Results must disclose method/confidence; no language-model calls are assumed. |
| Geospatial | Coordinate parsing, distance/haversine/bearing, radius and point-in-polygon tests, nearest neighbour, bounding box/centroid/area/buffer, geohash and GeoJSON. Requires geometry support. |
| Fuzzy matching and survivorship | Similarity/phonetic/token deduplication, similar-value clustering, canonical merging, survivorship/golden records and fuzzy joins. Integrate existing entity-resolution analysis rather than create inconsistent answers. |
| External enrichment | Historical exchange rates, IP geography, company/domain lookup, geocoding/reverse geocoding, coordinate timezone and calendar/reference enrichment. Requires credentials, network policy and explicit cost/rate-limit handling. |
| Extended reshape/combine | Beyond existing pivot/unpivot/split: richer nested/array reshape, transpose/stack/unstack, split-to-tables, positional merge, temporal/range and other specialised join variants. |
| Advanced sampling | Stratified/systematic/cluster/reservoir/balanced sampling, top-N-per-group, train/test and time/value/condition-based splits, as not already covered by basic sample steps. |

These are business family requirements. Implementation must reconcile individual operations against current steps and the registry before claiming an exact remaining count; similarly named tools are not automatically semantically equivalent.

<!-- PAGE -->
# Backlog: formulas and remaining breadth

## PL-37 - Formula language and authoring
The roadmap's broad Excel-style ambition remains incomplete. Missing named families include financial functions such as PV/IRR/XNPV, advanced statistical/percentile/LINEST functions, multi-table lookup functions such as VLOOKUP/INDEX and window functions. Add cell references such as A1/$A$1 only with defined recipe semantics, editor autocomplete/signature help and cross-derived-column dependencies/cycle detection. Current errors commonly become null with a count; first-class spreadsheet error cells require a separate decision. [S03 Phase 14]

## Phase 16 breadth beyond the absent major families
The complete category ambition includes the following additional areas. Many have working subsets today; the appendix is the current named inventory, not proof that every item in the old wish list shipped.

| Category group | Remaining breadth to reconcile and prioritise |
|---|---|
| Numeric and temporal | Robust/z-score scaling, quantile/frequency buckets, running changes, currency/unit conversion, holiday calendars, fiscal-period extensions, date spines and missing-date filling. Basic rescaling, percent-of, business-day calculations and fiscal year/quarter tools already exist. |
| Missing data | Forward/backward fill, linear/spline interpolation, mean/median/mode imputation and null-heavy column removal. Constant and cross-column filling already exist. |
| Aggregation and join | Rich collection/positional aggregates, weighted averages, correlation/covariance/percentiles; specialised semi/anti/as-of/range/set-operation experiences beyond current steps. |
| Cleansing | Address parsing/standardisation, currency/unit reference standardisation, swapped-column correction and richer lookup-based cleansing. Basic name splitting, country/postal cleanup and mojibake repair already exist. |
| Validation/assertions | Referential integrity, monotonicity, cross-total assertions, schema/distribution contracts, quarantine/flag/fail integration and custom formula assertions beyond the current 9 tools and 8 quality rule types. |
| Encoding and privacy | Reversible tokenisation, surrogate-key/UUID generation and any additional algorithms beyond current coverage. MD5, SHA variants, HMAC-SHA-256, masking and consistent pseudonymisation already exist. |
| Code escape hatches | Richer regex/jq-style JSON, inline lookup tables, explicit HTTP enrichment, safe file transforms, template rendering and custom plugins. SQL/notebooks/formulas/YAML already cover part of this ambition. |
| Metadata and productivity | Column descriptions/tags, ownership/glossary/classification editing, data dictionaries, schema snapshots/comparison, step notes, templates, branches and merges. Existing catalog, governance and YAML support are partial foundations. |

## Deliberate distinctions
SQL workbench completion is implemented; formula-bar completion is not. Workflow date macros exist; reusable Studio recipe macros/templates remain planned. Rule checking exists; the complete proposed assertion-tool set does not. These overlaps must be resolved through acceptance criteria, not by summing differently named catalogue entries.

<!-- PAGE -->
# Backlog: sources, files and write-back

## PL-38 - Source coverage and evidence
Broaden verified connector coverage toward the original approximately 250-source ambition while preserving tiers. Obtain real captured sessions before adding tier-3 evidence; run credentialed vendor checks for SaaS paths. Test each optional warehouse driver. Nine declared but unavailable engines are Cassandra, ScyllaDB, Couchbase, Redis, ArangoDB, HBase, Aerospike, Amazon Timestream and HDFS. gRPC requires its own client/reflection implementation. Streaming/queue/CDC and inbound ingestion are covered by PL-31. [S01, S03]

The original catalogue wish list also names table/lakehouse integrations and binary formats beyond the current readers. Delta Lake, Iceberg/Hudi and catalogue-specific behaviour must be validated per connector rather than inferred from storage access. Protobuf, MessagePack, HDF5, DBF, HTML tables and syslog are not established as working upload readers by the inspected registry; treat each as an unfulfilled catalogue aspiration pending an implementation decision, not as an available capability.

## PL-39 - File-ingestion completion
Add PDF table extraction through a maintained layout engine and define supported document structures. Enable/test SPSS .sav, ODS and 7-Zip with required packages. Add paste-from-clipboard dataset ingestion. Complete resumable UI and durable sessions through P2/P3. Consider full duplicate detection during streaming only with an explicit resource model; the present omission is honest. Rich statistical-file label fidelity and other original format-specific aspirations require explicit acceptance rather than an assumption from basic readability.

## PL-40 - Write-back expansion and assurance
The roadmap names file/object-storage, REST/SaaS, NoSQL and warehouse write-back, but the handoff deliberately keeps file-backed edits as replayable recipes. Such destructive source expansion is deferred design scope, not an approved universal write capability. It needs source-specific identity, concurrency, rollback, rate-limit and approval rules.

Unbuilt SQL edit kinds include column retyping, primary-key changes, indexes and constraints. Additional gaps are three-way conflict-resolution UX, savepoints per logical group and live PostgreSQL/MySQL write-back validation. Existing operations remain a single change-set transaction with dialect-specific DDL caveats.

## PL-41 - Explicitly bounded execution choices
Moving notebooks to a background worker is a future option if long-running cells are required; current request/time limits are deliberate. An advanced code editor is also optional, not required merely because the current editor is a text area. IR-only/pushdown integration belongs to P9; no deferred architecture choice should be made implicitly while completing another feature.

<!-- PAGE -->
# Business acceptance and traceability

Each acceptance case needs named users, realistic data, expected results and preserved evidence. The checks below specify business acceptance; they are not a claim that this document-authoring session executed each workflow.

| UAT | Scenario and pass condition | Requirements / outcome |
|---|---|---|
| UAT-01 | Viewer cannot edit or access another tenant; scoped read token cannot mutate even for an admin owner. | BR-01-08; NFR-02; BO-04/06 |
| UAT-02 | Upload leading-zero identifiers, exact decimals and ambiguous dates; preserve meaning and require unresolved decisions. | BR-12-17; NFR-01/10; BO-03 |
| UAT-03 | Build and rerun a cleanup/join/calculation recipe; preview and full result reconcile to expected rows/types/totals. | BR-18-25; BO-01/03 |
| UAT-04 | Feed known invalid records; verify warning versus quarantine handling and comparison/test history. | BR-26-33; BO-03 |
| UAT-05 | Execute a dependency workflow, failure/retry and dated backfill; inspect states and output references. | BR-34-41; BO-05/07 |
| UAT-06 | Propose a governed definition change; unauthorized direct edit is refused; approval and actor history are visible. | BR-42-49; BO-04 |
| UAT-07 | Generate reports and publish to the actual target; reconcile destination rows/totals and failed-delivery evidence. | BR-50-57; BO-07 |
| UAT-08 | Query in read-only mode; reject forbidden writes. Stage identified table edits; conflict prevents unsafe commit. | BR-58-65; BO-03/04 |
| UAT-09 | A novice completes the P2 flow; restart a gateway during upload; stop/recover the worker under P3. | PL-01-10; BO-02/05 |
| UAT-10 | Validate the deployment's actual IdP/MFA flows, backup restore and restricted policy views. | PL-11-23; NFR-02/03/06 |
| UAT-11 | Publish snapshots, AS OF query, identity-aware diff, append rollback and clock-shifted replay; enforce historical erasure/access. | PL-29; BO-08 |
| UAT-12 | Confirm metric consistency/contract refusal; CDC restart/duplicates; concurrent editing convergence; optimized-result equivalence. | PL-30-34; BO-03/05/08 |

## Release gates
Current development requires the full repository verification gate and honest reporting of passed, failed, skipped and unavailable checks. Production adoption additionally requires live evidence for the chosen sources, destinations, runtime and identity system. Future features need their own UAT before the corresponding requirements move to Available. No missing prerequisite counts as a pass. [S01, S04]

<!-- PAGE -->
# Rollout, risks and decisions

## Recommended adoption sequence
1. **Discovery:** select real recurring workflows, source/target systems, owners, quality controls and access boundaries. Confirm required capabilities and avoid relying on speculative items.
2. **Controlled pilot:** validate source credentials, supported readers and a reconciled end-to-end output. Train analysts on previews, missing values, tiers and execution states.
3. **Unattended operations:** complete/accept runtime supervision, notification routing, durable uploads and backup recovery. Assign an operator and incident procedure.
4. **Governed expansion:** add required enterprise identity, policy simulation, approval depth and performance evidence before sensitive or large deployments.
5. **Depth increments:** introduce historical versions, semantic contracts, CDC and advanced collaboration only after their acceptance gates pass.

| Risk | Impact | Mitigation / accountable role |
|---|---|---|
| Documentation overstates readiness | Buyer depends on unavailable features. | Keep status/evidence beside each capability; product owner. |
| Connector/BI service variability | Failed or incomplete extraction/delivery. | Credentialed pilot and per-source reconciliation; integration owner. |
| Idle worker or lost upload state | Scheduled outputs missing; interrupted imports. | P3 supervision/heartbeats/durability and operator ownership. |
| Ambiguous or lossy data interpretation | Incorrect business totals or identities. | Explicit ingest decisions and owner-approved control totals; steward. |
| Unsafe live-table or historical erasure | Irrecoverable data change or false deletion claim. | Identity/concurrency/review controls and P6/P7 lifecycle acceptance; data owner/security. |
| Scale assumptions exceed evidence | Slow previews, memory pressure or missed windows. | P5 workload baseline and resource limits; platform owner. |
| Overlapping roadmaps obscure scope | Duplicate or skipped delivery. | Maintain one requirement/status mapping; product owner. |

## Decisions required for a signed BRD
Name sponsor, product owner and operational owners; confirm first target segment and hosting model; choose required integrations and verification thresholds; set workload/SLA/RPO/RTO/retention targets; decide public sharing policy and native-PDF versus print path; approve identity requirements, data classifications and erasure expectations; prioritise tool families; fund/support the rollout and change process. None of these decisions is fabricated here.

**Sign-off roles:** business sponsor (outcomes/scope), product owner (priority), data owner (definitions/controls), security/governance (access/retention), engineering/operations (feasibility/run/recovery), UAT lead (acceptance evidence). Approval names and dates remain pending business review.

<!-- PAGE -->
# Source reconciliation and glossary

## Contradictions resolved deliberately
| Evidence conflict | Resolution applied in this BRD |
|---|---|
| Roadmap opening says not started; later sections and handoff mark delivery. | Use current code and handoff ledger. P0/P1 are also recorded complete in the newer readiness plan. |
| Handoff/roadmap mention both 167 and 173 tools. | Executable registry and generated reference both show 173; six nested-data tools explain the increase. Phase 16 remains partial. |
| Earlier formula milestone says 87 functions. | Current expression registry has 186 functions; parser has 207 accepted names including aliases. Avoid treating those as equal inventories. |
| Handoff overview mentions 30 migrations; newer P1 adds 0031. | Identity features follow the newer code/session record; the overview's count is stale. |
| Older guides say basic uploads, no user management and placeholder Settings. | Current reader registry, People/Organisations/Settings and P1 identity implementation supersede those descriptions. |
| Phase 07 lists SSO; security document says planned. | Backend groundwork is partial; end-to-end supported enterprise SSO is P4, without recorded live IdP assurance. |
| P1 is done but session inventory/throttling are not evidenced. | Token-version sign-out is delivered; session list/expiry display are residuals and throttling an optional candidate. |
| P8 names pie/table/KPI capabilities already in code. | Treat P8 as refinement/extension; do not relabel current chart types as absent. |
| Phase 18 suggests next; newer plan/commits advance P2. | P2 is now partially delivered, though the plan header still says next. Phase 18 remains P7/product-depth work with its accepted scope. |
| P9 calls cutovers pre-approved; Phase 18 explicitly defers them. | Keep them planned for deliberate P9 work, excluded from incidental Phase 18 implementation. |

## Business glossary
**ETL:** extract, transform and load data. **Dataset:** a stored, inspectable collection of data. **Recipe/pipeline:** reusable ordered preparation logic. **Workflow/DAG:** dependent operations coordinated as a graph. **Lineage:** where data came from and how it changed. **Quarantine:** separation of failing records. **Pushdown:** execute supported preparation at the source. **CDC:** consume database changes from a log. **Semantic layer:** shared metric definitions. **Data contract:** producer/consumer agreement on data expectations. **Snapshot/pin:** immutable data version / reference to the exact version used. **Write-back:** controlled changes to an external system's live data. **IR:** shared internal representation of transformations. **Tier:** evidence level for a connector, separate from availability.

<!-- PAGE -->
# Evidence register

Sources are local repository documents and implementation paths inspected for this BRD at baseline `79eb302`. References identify evidence to revisit, not external endorsements. No market-size, competitor or regulatory claims rely on unperformed research.

| Ref | Source and purpose |
|---|---|
| S01 | `AGENTS.md`; `docs/HANDOFF.md` - authority order, invariants, delivery ledger, limitations and session history through P1. |
| S02 | `docs/plans/production-readiness-workflow.md` - P0-P9 scope, current sequencing and optional improvements. |
| S03 | `docs/roadmap-v2.md` - Phase 08-23 ambitions, explicit exclusions, source/tool catalogues and seven exploratory bets. |
| S04 | `docs/plans/phase-18-review-requirements.md` - accepted versioning, replay, erasure, concurrency and acceptance requirements. |
| S05 | `docs/security.md` - implemented identity/security posture and planned enterprise identity. |
| S06 | `services/service-auth/`; `services/service-access/`; `services/service-enterprise/`; `apps/web/src/features/settings/` - identity, roles, tenant/policy controls and delivered Settings. |
| S07 | `services/service-connectors/`; `services/service-extraction/`; `services/service-ingestion/` - registry, formats/readers, extraction and ingestion evidence. |
| S08 | `docs/transformation-tools.md`; `services/service-transformations/src/service_transformations/tools/`; `ir/expressions.py`; `formula/parser.py`; `apps/web/src/features/studio/` - exact tool/function inventories and preparation behaviour. |
| S09 | `services/service-quality/`; `services/service-comparisons/`; `services/service-lineage/`; `services/service-intelligence/`; `services/service-observability/` - quality, tests, provenance and deterministic analysis. |
| S10 | `services/service-workflows/`; `services/service-schedules/`; `services/service-notifications/`; `apps/web/src/lib/runtime-health.ts` - execution, recurrence and runtime visibility. |
| S11 | `services/service-governance/`; `services/service-reporting/`; `services/service-enterprise/` - definition reviews, audit, catalog metadata, policies and lifecycle. |
| S12 | `services/service-reporting/`; `services/service-destinations/`; `apps/web/src/features/reporting/components/dashboards-page.tsx` - reports, charts, target publication and explicit missing share viewer. |
| S13 | `services/service-workbench/`; `services/service-writeback/`; relevant handoff/roadmap sections - SQL, notebooks and guarded table changes. |
| S14 | `docs/features-guide.md`; `docs/project-case-study.md` - original business narrative and basic workflows; superseded where newer evidence differs. |
| S15 | Commits `ab924f3`, `85492d0`, `79eb302`; type-fidelity tests, project-checklist/workspace-menu components and pipeline naming UI - initial P2 implementation ahead of the ledger. |

**Document validation:** current connector/tool counts were read from executable registries. The PDF is generated from this maintained text, with page layout and extracted text checked separately. Status evidence is a point-in-time inventory; it must be refreshed when features ship.

<!-- PAGE -->
# Appendix: current transformation tools

The following pages list every current named tool, grouped by the executable registry's category. These are the 173 tool entries, not an additional promise that every original roadmap operation or every SQL dialect is supported. Use the in-product tool description and parameter/type checks to determine applicability. [S08]

{{TOOLS_A}}

<!-- PAGE -->
# Appendix: current tools, continued

{{TOOLS_B}}

<!-- PAGE -->
# Appendix: current tools, continued

{{TOOLS_C}}

<!-- PAGE -->
# Appendix: current tools, continued

{{TOOLS_D}}

<!-- PAGE -->
# Appendix: connector readiness

The registry contains 211 entries: 50 tier-2 and 161 tier-4. In the inspected Python environment, 155 entries report available. Availability means the implementation prerequisites it checks are present; it is not proof of successful authentication or a live vendor read. Source lists should always be filtered by the deployment's actual capability report. [S07]

{{CONNECTORS}}

## Verification tiers
**Tier 1:** real-instance/live CI verification. **Tier 2:** controlled fixture/container verification; the current 50 include vendor-contract fixtures and self-hosted database/container paths. **Tier 3:** replay of a genuinely captured session. **Tier 4:** documentation/specification only. There are no tier-1 or tier-3 entries in the inspected registry.

## Adoption checklist for a required connection
Confirm the exact vendor/product and driver; verify the permitted authentication method and secret handling; test discovery and complete pagination; validate types and incremental boundaries; reconcile a realistic read with the source; test the required destination separately; capture failure/retry behaviour and operational ownership. These are deployment acceptance tasks, not automatic consequences of catalogue inclusion.

**End of BRD.** Status changes should update the requirement register, relevant source document and acceptance evidence together.
