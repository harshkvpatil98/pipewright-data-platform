# Terraform provider for Pipewright

Manage a Pipewright deployment as code: projects and who may open them,
connections (secrets written, never read back), datasets uploaded from files,
recipes written as recipe YAML, schedules, checks, workflows and API tokens.
Every resource is read back on each plan, so `terraform plan` shows what was
changed in the app since the last apply, and applying puts it back.

```hcl
terraform {
  required_providers {
    pipewright = { source = "harshkvpatil98/pipewright" }
  }
}

provider "pipewright" {
  url = "https://pipewright.example.com"   # or PIPEWRIGHT_URL
  # token: PIPEWRIGHT_TOKEN, an API token from Your settings → API tokens
}
```

Use an API token limited to the projects the configuration manages and given
an expiry; making projects needs one that is not limited. A token is held to
its owner's role in each project.

## Resources

| Resource | Settings | Import as |
|---|---|---|
| `pipewright_project` | `name`, `description`, `status` (active, draft, archived), `requires_approval`; gives `slug` | `<project id>` |
| `pipewright_project_member` | `project_id`, `username`, `role` (viewer, operator, editor, admin) | `<project id>/<membership id>` |
| `pipewright_connection` | `project_id`, `name`, `connector_type`, `config` (jsonencode, no secrets), `secrets` (jsonencode, sensitive, never read back), `status` | `<project id>/<id>` |
| `pipewright_file_dataset` | `project_id`, `name`, `source` (a file's path), `source_hash` (`filesha256(source)`); gives `row_count`, `column_count`. A new file replaces the dataset. | — |
| `pipewright_recipe` | `project_id`, `dataset_id`, `name`, `description`, `yaml` (recipe YAML; a step's `name:` is its note); gives `revision`, `output_dataset_id`. Compared by its steps, so formatting is never a change; a save in the app since the plan stops the apply. | `<project id>/<id>` |
| `pipewright_schedule` | `project_id`, `name`, `schedule_type` (transformation_pipeline_run, postgres_publish, connector_schema_watch), `cron_expression`, `timezone`, `enabled`, `target` (jsonencode, such as `{pipeline_id = ...}`) | `<project id>/<id>` |
| `pipewright_check` | `project_id`, `dataset_id`, `name`, `description`, `rule_type`, `severity`, `config` (jsonencode), `enabled` | `<project id>/<id>` |
| `pipewright_workflow` | `project_id`, `name`, `description`, `trigger_type`, `cron_expression`, `timezone`, `enabled`, `tasks` and `links` (jsonencode lists) | `<project id>/<id>` |
| `pipewright_api_token` | `name`, `scope`, `project_ids`, `expires_in_days`; gives `secret` (sensitive), `prefix`, `expires_at`. Any change makes a new token; destroying it revokes it. | — |

## Data sources

| Data source | Finds | Gives |
|---|---|---|
| `pipewright_project` | by `id` or `name` | `slug`, `description` |
| `pipewright_dataset` | in `project_id`, by `id` or `name` | `row_count`, `column_count` |
| `pipewright_connection` | in `project_id`, by `name` | `id`, `connector_type`, `status` |

## An example

[`examples/main.tf`](examples/main.tf) builds a project with a dataset from a
file, a connection, a recipe, a schedule, a check and a workflow.

## Developing

```bash
go vet ./... && go test ./...                       # unit tests
TF_ACC=1 PIPEWRIGHT_URL=http://127.0.0.1:8100 PIPEWRIGHT_TOKEN=pw_... \
  PIPEWRIGHT_TEST_MEMBER=someone go test ./internal/provider -run TestAcc -v
```

The acceptance tests run real Terraform against a real gateway: they apply
everything, plan again and fail on any change, import each resource, put back
a change made in the app, change a recipe and destroy it all. CI runs them on
every change (the `terraform` job). Publishing the provider to the Terraform
Registry is the owner's decision and has not been done.
