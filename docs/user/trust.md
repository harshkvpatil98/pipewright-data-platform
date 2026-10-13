# Trust

Know the data is right, and hear about it when it is not.

## Checks

A check is a rule the data must pass, such as "every order has an email" or "amount is between 0 and 10,000". Add checks to a dataset, then run them by hand, on a schedule or as a workflow task. Each run shows how many rows failed each check.

Turn on **quarantine** and failing rows are set aside in their own dataset while the good rows carry on. A failing check opens an [incident](#incidents).

## Comparisons

Save a statistical comparison between two datasets, such as "the average order is the same as last month", and run it again after the data changes. A comparison shows whether a difference is beyond chance, not why it happened.

## Incidents

An incident is a problem that needs a person: a failed check, data that has not arrived, a number far from its usual range, or a background worker that stopped. Everyone who can act on it is told, in the app and on the project's alert channels.

**Acknowledge** an incident to show someone is on it, **assign** it to a person, and **resolve** it when fixed. Many incidents close by themselves when the problem clears. A problem that keeps happening counts up on one incident rather than opening a new one each time.

## Schema changes

Columns added, removed or retyped at a source since its last import. Breaking changes are marked, because they can stop recipes working. Acknowledge a change once you have dealt with it.

## Policies

Policies decide who sees what:

- **Row rules** hide rows from a role, such as "viewers see only the EU".
- **Column rules** hide a column from a role, or mask it: partly hidden (`an***@example.com`), replaced with `[redacted]`, or turned into a code that still groups and joins.

A policy applies wherever rows reach a person: the dataset page, charts and dashboards (public links read as a viewer), the Studio, SQL over a version, the assistant, comparisons, downloads and deliveries. Column names still appear in lineage and recipes, which describe the shape of the data, not its values. **Policy simulation** shows exactly what a role or one person would see before you grant it.

Policies also set **retention** (how long old runs, history and versions are kept) and handle **erasure**: correcting or removing one person's data everywhere it appears, with a report of anything that could not be done.

## Approvals

In a project that needs approval, changes to recipes, workflows and checks wait here for someone to accept them. Running things is never blocked; only changing what they are.

## Audit log

Who changed what in the project, and when, in plain sentences: "Ann ran a recipe", "Bo deleted the dashboard Weekly sales". Refused attempts are recorded too. Looking at things is not recorded; changing them is.
