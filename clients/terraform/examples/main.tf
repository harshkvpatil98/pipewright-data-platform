terraform {
  required_providers {
    pipewright = { source = "harshkvpatil98/pipewright" }
  }
}

variable "warehouse_password" {
  type      = string
  sensitive = true
}

provider "pipewright" {
  url = "https://pipewright.example.com"
}

resource "pipewright_project" "sales" {
  name        = "Sales as code"
  description = "Made by Terraform."
}

resource "pipewright_file_dataset" "orders" {
  project_id  = pipewright_project.sales.id
  name        = "Orders"
  source      = "${path.module}/orders.csv"
  source_hash = filesha256("${path.module}/orders.csv")
}

resource "pipewright_connection" "warehouse" {
  project_id     = pipewright_project.sales.id
  name           = "Warehouse"
  connector_type = "postgresql"
  config = jsonencode({
    host     = "warehouse.example.com"
    port     = 5432
    database = "sales"
    username = "reporting"
  })
  secrets = jsonencode({ password = var.warehouse_password })
}

resource "pipewright_recipe" "shipped" {
  project_id = pipewright_project.sales.id
  dataset_id = pipewright_file_dataset.orders.id
  name       = "Shipped orders"
  yaml       = <<-YAML
    version: 1
    steps:
      - step: filter_rows
        name: Only what shipped
        with:
          conditions:
            - column: status
              operator: equals
              value: shipped
      - step: sort_rows
        with:
          columns: [amount]
          ascending: false
  YAML
}

resource "pipewright_schedule" "nightly" {
  project_id      = pipewright_project.sales.id
  name            = "Nightly shipped orders"
  cron_expression = "0 2 * * *"
  timezone        = "Europe/London"
  target          = jsonencode({ pipeline_id = pipewright_recipe.shipped.id })
}

resource "pipewright_check" "amount" {
  project_id = pipewright_project.sales.id
  dataset_id = pipewright_file_dataset.orders.id
  name       = "Every order has an amount"
  rule_type  = "not_null"
  config     = jsonencode({ column = "amount" })
}

resource "pipewright_workflow" "weekly" {
  project_id = pipewright_project.sales.id
  name       = "Weekly refresh"
  tasks = jsonencode([
    { node_key = "ship", name = "Shipped orders", node_type = "transformation",
    config = { pipeline_id = pipewright_recipe.shipped.id } },
  ])
}

resource "pipewright_project_member" "viewer" {
  project_id = pipewright_project.sales.id
  username   = "ana"
  role       = "viewer"
}

resource "pipewright_api_token" "reporting" {
  name            = "Reporting script"
  scope           = "read"
  project_ids     = [pipewright_project.sales.id]
  expires_in_days = 30
}

data "pipewright_dataset" "orders" {
  project_id = pipewright_project.sales.id
  name       = pipewright_file_dataset.orders.name
}

output "orders_rows" {
  value = data.pipewright_dataset.orders.row_count
}

output "reporting_token_prefix" {
  value = pipewright_api_token.reporting.prefix
}
