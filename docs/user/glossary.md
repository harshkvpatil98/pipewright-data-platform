# Glossary

Every word Pipewright uses, with one meaning each. If a screen ever uses a word differently, that is a fault worth reporting.

| Word | What it means |
|---|---|
| Project | A space for one team or subject. Everything else lives inside one. |
| Source | Where data comes from: an uploaded file, a database, an app, an API or a live feed. |
| Connector | A kind of source in the catalogue, such as PostgreSQL, Stripe or S3. Each says how well it is tested. |
| Import | Bringing a table from a connected source into a dataset, once or on a schedule. |
| Live feed | Data that arrives by itself, read every few seconds: a database's changes, a queue's messages or posts to a webhook. |
| Live recipe | A recipe that runs on a live feed's events as they arrive, to clean, look up or summarise them by time. |
| Window | A stretch of time a live recipe summarises over, such as each minute. A window is final once late events have had their chance. |
| Dataset | A table of data in a project. |
| Version | One saved state of a dataset. Every change makes a new one, and old ones stay readable. |
| Recipe | The ordered steps that turn one dataset into another. |
| Step | One change inside a recipe, such as removing empty rows. |
| Run | One go of a recipe, an import, a workflow, a check or a delivery. |
| Runs at once | How many runs a project may have going together. Queued work waits its turn; a person's runs go first. |
| Statistics | What is known about a dataset's or a table's values: how many rows, how often each column is empty, how its values spread. Plans are estimated from them. |
| Estimate | The rows a step or a query is expected to give, worked out from statistics. One with nothing to work from says it is a guess. |
| Query across sources | One SQL query over tables in several databases and datasets; each runs its own part, and joins between them run here. |
| Incremental run | A recipe run that computes only what changed since the last run (rows added, or a partition's rows), and gives what a full run would. |
| Partition | Rows that share one value of a chosen column, such as a region or a day; an incremental run computes only the partitions whose rows changed. |
| Workflow | Tasks that run in order, by hand or on a schedule. |
| Schedule | When something runs by itself. |
| Check | A rule the data must pass, such as "every order has an email". |
| Incident | Something that went wrong and needs a person. |
| Schema change | A column added, removed or retyped at a source. |
| Contract | A promise about a dataset that new data must keep: its columns, rows and how often it is refreshed. |
| Destination | Where data is delivered: a database, a file store or a BI tool. |
| Dashboard | A page of charts that answer one question together. |
| Chart | A saved question about a dataset, drawn as a picture. |
| Report | A file sent by email or Slack on a schedule. |
| Metric | A number defined once and used everywhere, so every chart agrees. |
| Policy | A rule about who sees which rows and columns, or how long data is kept. |
| Change request | An edit waiting for someone's approval, listed under Approvals. |
| Suggestion | A change to a recipe sent for someone who may edit it to accept or decline. |
| Thread | A comment and its replies, on a thing or on one cell of a dataset; it resolves as a whole. |
| Member | A person with access to a project, as a viewer, operator, editor or admin. |
| Organisation | A group of people and projects kept apart from other groups. |

## Roles

| Role | Can |
|---|---|
| Viewer | See everything in the project, and change nothing. |
| Operator | Run recipes, imports and workflows, and handle incidents. |
| Editor | Create and change recipes, workflows and checks, and run them. |
| Admin | Everything, including who has access. |

A platform administrator also manages accounts and organisations for the whole server.
