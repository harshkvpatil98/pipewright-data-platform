# Glossary

Every word Pipewright uses, with one meaning each. If a screen ever uses a word differently, that is a fault worth reporting.

| Word | What it means |
|---|---|
| Project | A space for one team or subject. Everything else lives inside one. |
| Source | Where data comes from: an uploaded file, a database, an app, an API or a live feed. |
| Connector | A kind of source in the catalogue, such as PostgreSQL, Stripe or S3. Each says how well it is tested. |
| Import | Bringing a table from a connected source into a dataset, once or on a schedule. |
| Dataset | A table of data in a project. |
| Version | One saved state of a dataset. Every change makes a new one, and old ones stay readable. |
| Recipe | The ordered steps that turn one dataset into another. |
| Step | One change inside a recipe, such as removing empty rows. |
| Run | One go of a recipe, an import, a workflow, a check or a delivery. |
| Workflow | Tasks that run in order, by hand or on a schedule. |
| Schedule | When something runs by itself. |
| Check | A rule the data must pass, such as "every order has an email". |
| Incident | Something that went wrong and needs a person. |
| Schema change | A column added, removed or retyped at a source. |
| Destination | Where data is delivered: a database, a file store or a BI tool. |
| Dashboard | A page of charts that answer one question together. |
| Chart | A saved question about a dataset, drawn as a picture. |
| Report | A file sent by email or Slack on a schedule. |
| Metric | A number defined once and used everywhere, so every chart agrees. |
| Policy | A rule about who sees which rows and columns, or how long data is kept. |
| Change request | An edit waiting for someone's approval, listed under Approvals. |
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
