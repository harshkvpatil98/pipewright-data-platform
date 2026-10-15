# Using the API

Everything the app does, a script can do through the same API. This page shows how to sign in and walks through three common jobs: connecting a source and importing a table, running a recipe, and reading a dataset. The full reference, with every request and its fields, is under **Help → API reference**.

The examples use `curl` and `jq` in a terminal. Every example on this page is run against the API by an automated test whenever the product changes, so they work as written.

## Before you start

Set the address of your Pipewright, as you open it in a browser:

```bash
PIPEWRIGHT=https://pipewright.example.com
```

Every address in the API starts with `/api/v1`. Requests and answers are JSON. An error comes back with a status code and a `detail` that says what went wrong in words.

## Signing in

Scripts use an **API token** rather than a password. Make one in the app under **Your settings → API tokens**, or with the API as below. A token has a scope:

| Scope | Can |
| --- | --- |
| `read` | Read anything its owner can see, and change nothing |
| `write` | Also create, change and run things its owner may |
| `admin` | Also manage accounts, if its owner is an administrator |

A token never does more than the person who made it, and is held to the same organisation network list.

To make one with the API, sign in with your password to get a short session:

```bash
SESSION=$(curl -s -X POST "$PIPEWRIGHT/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d @- <<EOF | jq -r .access_token
{"username": "$USERNAME", "password": "$PASSWORD"}
EOF
)
```

Then make a token with it. The token's secret is shown this once, so keep it somewhere safe:

```bash
TOKEN=$(curl -s -X POST "$PIPEWRIGHT/api/v1/auth/tokens" \
  -H "Authorization: Bearer $SESSION" \
  -H "Content-Type: application/json" \
  -d @- <<EOF | jq -r .secret
{"name": "Nightly script", "scope": "write"}
EOF
)
```

Send the token with every request as `Authorization: Bearer $TOKEN`. Withdraw it under **Your settings** when the script no longer needs it.

If your account uses two-factor authentication, make the token in the app instead; signing in by password from a script stops at the second step.

## Example 1: connect a source and import a table

Make a project to work in:

```bash
PROJECT=$(curl -s -X POST "$PIPEWRIGHT/api/v1/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF | jq -r .id
{"name": "Sales"}
EOF
)
```

Connect a PostgreSQL database. The password is encrypted when it is saved and never sent back:

```bash
CONNECTION=$(curl -s -X POST "$PIPEWRIGHT/api/v1/projects/$PROJECT/extraction/connections" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF | jq -r .id
{"name": "Shop database", "connector_type": "postgresql",
 "config": {"host": "db.example.com", "port": 5432, "database": "shop",
            "username": "reader", "password": "$DB_PASSWORD"}}
EOF
)
```

Check Pipewright can reach it. The answer says whether it worked and, if not, why:

```bash
curl -s -X POST "$PIPEWRIGHT/api/v1/projects/$PROJECT/extraction/connections/$CONNECTION/test" \
  -H "Authorization: Bearer $TOKEN"
```

Set up an import of one table, then run it. Each run adds a version to the same dataset; set `load_mode` to `incremental` with a `cursor_column` to bring in only new rows each time:

```bash
IMPORT=$(curl -s -X POST "$PIPEWRIGHT/api/v1/projects/$PROJECT/extraction/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF | jq -r .id
{"connection_id": "$CONNECTION", "name": "Orders", "table": "orders",
 "load_mode": "full_refresh"}
EOF
)
```

```bash
DATASET=$(curl -s -X POST "$PIPEWRIGHT/api/v1/projects/$PROJECT/extraction/jobs/$IMPORT/run" \
  -H "Authorization: Bearer $TOKEN" | jq -r .dataset_id)
```

The answer also gives `rows_extracted` and `total_rows`, and a `run_id` to look the run up later.

## Example 2: run a recipe

A recipe is a list of steps. This one removes repeated rows and puts the largest orders first. Steps are easiest to build in the Studio and save; their settings are then visible in the recipe's file view, ready to copy.

```bash
RECIPE=$(curl -s -X POST "$PIPEWRIGHT/api/v1/projects/$PROJECT/datasets/$DATASET/pipelines" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF | jq -r .id
{"name": "Clean orders", "status": "active",
 "steps_json": [
   {"step_type": "remove_duplicates", "config": {}},
   {"step_type": "sort_rows", "config": {"columns": ["amount"], "ascending": false}}
 ]}
EOF
)
```

Run it. The answer is the finished run and the dataset it made:

```bash
RUN=$(curl -s -X POST "$PIPEWRIGHT/api/v1/projects/$PROJECT/pipelines/$RECIPE/run" \
  -H "Authorization: Bearer $TOKEN" | jq -r .run.id)
```

Look the run up later, for its status and what each step did:

```bash
curl -s "$PIPEWRIGHT/api/v1/projects/$PROJECT/runs/$RUN" \
  -H "Authorization: Bearer $TOKEN"
```

## Example 3: read a dataset

The first rows, as JSON:

```bash
curl -s "$PIPEWRIGHT/api/v1/projects/$PROJECT/datasets/$DATASET/preview" \
  -H "Authorization: Bearer $TOKEN"
```

Every row, as a file. Use `format=parquet` for Parquet, and add `&version=2` for an earlier version:

```bash
curl -s "$PIPEWRIGHT/api/v1/projects/$PROJECT/datasets/$DATASET/download?format=csv" \
  -H "Authorization: Bearer $TOKEN" -o orders.csv
```

The project's row and column policies apply to the API exactly as they do in the app: a token sees what its owner may see.

## Example 4: promise what a dataset holds

A [contract](trust.md#contracts) is a promise about a dataset that new data must keep. Ask for the dataset's contract; with none yet, `draft` holds promises written from its current data:

```bash
curl -s "$PIPEWRIGHT/api/v1/projects/$PROJECT/datasets/$DATASET/contract" \
  -H "Authorization: Bearer $TOKEN"
```

Save one. With `"enforcement": "stop"`, an import or recipe run whose data breaks it fails with `409` and the reasons, and the current data stays. The answer says whether the current data keeps it:

```bash
curl -s -X PUT "$PIPEWRIGHT/api/v1/projects/$PROJECT/datasets/$DATASET/contract" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{"enforcement": "stop",
 "terms": {"columns": [{"name": "id", "kind": "whole_number", "always_filled": true, "no_repeats": true},
                       {"name": "amount", "kind": "decimal_number", "lowest": 0}],
           "rows_at_least": 1}}
EOF
```

## Example 5: receive events as they happen

A [live feed](data.md#live-feeds) takes data as it arrives. The simplest is a webhook: an address your systems post to. Its `token` comes back once, here, and is never shown again:

```bash
HOOK=$(curl -s -X POST "$PIPEWRIGHT/api/v1/projects/$PROJECT/streams" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF | jq -r .token
{"name": "Order events", "kind": "webhook"}
EOF
)
```

Post an event to it. No sign-in: the address is the permission. An `Idempotency-Key` makes a post sent twice count once:

```bash
curl -s -X POST "$PIPEWRIGHT/api/v1/hooks/$HOOK" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-1001" \
  -d '{"order": 1001, "region": "north", "amount": 12.5}'
```

Each feed lists how many events it holds, when it last saved, and how sure it is that each event is saved once (`guarantee`):

```bash
curl -s "$PIPEWRIGHT/api/v1/projects/$PROJECT/streams" \
  -H "Authorization: Bearer $TOKEN"
```

Database changes and queues are made the same way, with a `kind` and its `settings`; `GET /api/v1/projects/$PROJECT/live/kinds` lists every kind with the settings it needs, and `POST /api/v1/projects/$PROJECT/streams/try` checks settings before you save them. A change-capture feed also names a `connection_id` and its `tables`. Add a live recipe, for example orders per minute by region, with `POST /api/v1/projects/$PROJECT/streams/$FEED/recipes`, and read its windows with `GET /api/v1/projects/$PROJECT/streams/$FEED/recipes/$LIVE_RECIPE/results`.

## Saving without replacing someone else's work

A recipe has a `revision`, which goes up with every save. Send the one you started from as `expected_revision` when you change a recipe (`PATCH /api/v1/projects/$PROJECT/pipelines/$RECIPE`), and a save made since by someone else is not replaced: the answer is `409`, saying who saved and when. Read the recipe again, then save. Without `expected_revision` a save replaces whatever is there.

Someone who may not change a recipe can suggest a change instead: `POST /api/v1/projects/$PROJECT/pipelines/$RECIPE/suggest` with a `title`, an optional `note` and the `steps_json` they propose. It waits under Approvals for someone else to accept or decline.

## Moving a project's work

A bundle is a project's recipes, checks, contracts, metrics, charts, dashboards, workflows and schedules in one JSON file, with no data or passwords. Download one:

```bash
curl -s "$PIPEWRIGHT/api/v1/projects/$PROJECT/bundle" \
  -H "Authorization: Bearer $TOKEN" -o project-bundle.json
```

To bring it into another project, send it as `{"bundle": <the file>, "mapping": {}}` to `POST /api/v1/projects/$PROJECT/bundle/preview`, which says what would be made, what matched by name and what is missing, and changes nothing; then to `POST /api/v1/projects/$PROJECT/bundle/import`. For a dataset the project lacks, add a stand-in to `mapping`, for example `{"dataset:Orders": "<a dataset id in this project>"}`.

## Webhooks

A webhook sends each event you choose to an address of yours, as it happens. Add one under **Overview → Alerts → Add a channel → A webhook**; its signing secret is shown once, after you save.

Each event is a `POST` with a JSON body:

```json
{"id": "5f0c…", "type": "workflow_run_failed", "occurred_at": "2026-10-15T09:12:03+00:00",
 "project": {"id": "…", "name": "Shop"}, "title": "Workflow failed",
 "message": "Workflow “Nightly” failed: …", "level": "error"}
```

The `id` is the same on every try of one event, so you can ignore one you have already handled. The request carries `Pipewright-Signature: t=<seconds>,v1=<signature>`. Check it before you trust the event: the signature is HMAC-SHA256 of `t`, a full stop and the raw body, made with your secret. In Python:

```python
import hashlib
import hmac
import time


def came_from_pipewright(secret: str, signature_header: str, body: bytes) -> bool:
    parts = dict(item.split("=", 1) for item in signature_header.split(","))
    timestamp = int(parts["t"])
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    recent = abs(time.time() - timestamp) <= 300  # refuse an old event replayed
    return recent and hmac.compare_digest(expected, parts["v1"])
```

Answer with any `2xx` once you have the event. An answer of `5xx`, `408` or `429`, or none within five seconds, is tried twice more, a minute and then five minutes later; any other answer is taken as a refusal and not repeated. **Deliveries** on the channel shows every try and its result, and **New secret** replaces the secret at once.

## Embedding a dashboard

A dashboard can be shown inside a page of your own site. Open the dashboard, choose **Embed**, say where it will be shown and how long it lasts, and **Make a link**. You get the code to paste into your page, its link, and a signing secret, shown once. Turn the embed off at any time and every link to it stops at once. Only sites that whoever runs Pipewright lists in `EMBED_ALLOWED_ORIGINS` may show it in a frame.

The link made for you lasts as long as the embed. For a site where people sign in, make a short link as each page loads instead, signed with the embed's secret, and fix filters so each customer sees only their own rows. The link's token is a JSON Web Token signed with HS256, so any language's JWT library makes one. Its claims are the embed's `id`, an expiry, and any filters, which apply to every chart on the dashboard. In Python, with `pip install pyjwt`:

```python
import time

import jwt


def embed_src(pipewright: str, embed_id: str, secret: str, customer_id: str) -> str:
    claims = {
        "embed": embed_id,
        "exp": int(time.time()) + 600,  # ten minutes
        "filters": [{"column": "customer_id", "value": customer_id}],
    }
    return f"{pipewright}/embed/{jwt.encode(claims, secret, algorithm='HS256')}"
```

In Node, `jwt.sign({ embed, filters }, secret, { algorithm: "HS256", expiresIn: "10m" })` with the `jsonwebtoken` package makes the same token, and the Python client has `embed_link`. Nobody viewing the page can change a signed link, so they cannot widen its filters or stretch its expiry. A filter on a column a chart's data lacks shows that chart as not loaded, rather than every row. Filters take the dashboard's `operator`s (`equals` when left out, `in` with a list, and so on).

Add `?title=0` to leave the dashboard's name off, and `?theme=light` or `?theme=dark` to match your page. A link that has run out says so and asks the viewer to reload the page it was on.

## The Python client and command line

The repository's `clients/python` is a Python package with every API operation as a method and a `pipewright` command for the jobs people do most: list projects and datasets, upload and download, run a recipe or a workflow and wait for it, move a bundle, or call any operation.

```text
pip install -e clients/python
pipewright login https://pipewright.example.com --token pw_...
pipewright run workflow "Regional sales" Nightly --wait
```

Its README lists every command; in Python, `from pipewright import Client`. The methods are generated from this API's own reference, so they cannot fall behind it.

## Good to know

- **Finding ids.** `GET /api/v1/projects` lists projects, and `GET /api/v1/projects/$PROJECT/datasets` lists a project's datasets, each with its `id`. In the app, a page's **Technical details** shows the ids it is about.
- **Errors.** `401` means the token is missing, wrong or withdrawn; `403` that its owner may not do this, or it is a read token; `404` that the thing does not exist or is not visible to you; `409` that new data breaks a dataset's contract, so it was not saved, or that someone saved a recipe since you read it; `400` and `422` that the request needs changing, with the reason in `detail`.
- **Long jobs.** Imports and recipes answer when they finish. For work that runs on its own, such as a workflow, start it and then ask for the run until its `status` is `succeeded` or `failed`.
