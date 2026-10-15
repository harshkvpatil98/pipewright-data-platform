package provider

import (
	"context"
	"fmt"
	"os"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/providerserver"
	"github.com/hashicorp/terraform-plugin-go/tfprotov6"
	"github.com/hashicorp/terraform-plugin-testing/helper/acctest"
	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/plancheck"
	"github.com/hashicorp/terraform-plugin-testing/terraform"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/client"
)

// The acceptance tests run real Terraform against a real gateway: TF_ACC=1,
// PIPEWRIGHT_URL and PIPEWRIGHT_TOKEN (an API token that may make projects).
var testAccProtoV6ProviderFactories = map[string]func() (tfprotov6.ProviderServer, error){
	"pipewright": providerserver.NewProtocol6WithError(New("test")()),
}

func testAccPreCheck(t *testing.T) {
	for _, name := range []string{"PIPEWRIGHT_URL", "PIPEWRIGHT_TOKEN"} {
		if os.Getenv(name) == "" {
			t.Fatalf("%s is needed for the acceptance tests", name)
		}
	}
}

func testAPI(t *testing.T) *client.Client {
	api, err := client.New(os.Getenv("PIPEWRIGHT_URL"), os.Getenv("PIPEWRIGHT_TOKEN"))
	if err != nil {
		t.Fatal(err)
	}
	return api
}

const recipeYAML = `version: 1
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
      ascending: %t
`

func everything(name string, ascending bool) string {
	return fmt.Sprintf(`
resource "pipewright_project" "sales" {
  name        = %[1]q
  description = "Made by the acceptance tests."
}

resource "pipewright_file_dataset" "orders" {
  project_id  = pipewright_project.sales.id
  name        = "Orders"
  source      = "testdata/orders.csv"
  source_hash = filesha256("testdata/orders.csv")
}

resource "pipewright_connection" "warehouse" {
  project_id     = pipewright_project.sales.id
  name           = "Warehouse"
  connector_type = "postgresql"
  config         = jsonencode({ host = "db.example.com", port = 5432, database = "shop", username = "reader" })
  secrets        = jsonencode({ password = "not-a-real-password" })
}

resource "pipewright_recipe" "shipped" {
  project_id = pipewright_project.sales.id
  dataset_id = pipewright_file_dataset.orders.id
  name       = "Shipped orders"
  yaml       = %[2]q
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

resource "pipewright_api_token" "reporting" {
  name            = "Reporting script"
  scope           = "read"
  project_ids     = [pipewright_project.sales.id]
  expires_in_days = 30
}

data "pipewright_project" "sales" {
  name       = pipewright_project.sales.name
  depends_on = [pipewright_project.sales]
}

data "pipewright_dataset" "orders" {
  project_id = pipewright_project.sales.id
  name       = pipewright_file_dataset.orders.name
}

data "pipewright_connection" "warehouse" {
  project_id = pipewright_project.sales.id
  name       = pipewright_connection.warehouse.name
}
`, name, fmt.Sprintf(recipeYAML, ascending))
}

// importID reads "<project id>/<id>" for a resource from the state.
func importID(address string) resource.ImportStateIdFunc {
	return func(state *terraform.State) (string, error) {
		found, ok := state.RootModule().Resources[address]
		if !ok {
			return "", fmt.Errorf("%s is not in the state", address)
		}
		return found.Primary.Attributes["project_id"] + "/" + found.Primary.ID, nil
	}
}

func TestAccEverythingAProjectNeeds(t *testing.T) {
	name := "Terraform acceptance " + acctest.RandStringFromCharSet(8, acctest.CharSetAlphaNum)
	var projectID, checkID string
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			// Apply; afterwards the harness plans again and fails on any change.
			{
				Config: everything(name, false),
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("pipewright_project.sales", "status", "active"),
					resource.TestCheckResourceAttrSet("pipewright_project.sales", "slug"),
					resource.TestCheckResourceAttr("pipewright_file_dataset.orders", "column_count", "9"),
					resource.TestCheckResourceAttr("pipewright_connection.warehouse", "status", "active"),
					resource.TestCheckResourceAttr("pipewright_recipe.shipped", "revision", "1"),
					resource.TestCheckResourceAttrSet("pipewright_schedule.nightly", "next_run_at"),
					resource.TestCheckResourceAttr("pipewright_check.amount", "severity", "error"),
					resource.TestCheckResourceAttr("pipewright_workflow.weekly", "trigger_type", "manual"),
					resource.TestCheckResourceAttrSet("pipewright_api_token.reporting", "secret"),
					resource.TestCheckResourceAttrPair("data.pipewright_project.sales", "id", "pipewright_project.sales", "id"),
					resource.TestCheckResourceAttr("data.pipewright_dataset.orders", "row_count", "49"),
					resource.TestCheckResourceAttr("data.pipewright_connection.warehouse", "connector_type", "postgresql"),
					func(state *terraform.State) error {
						projectID = state.RootModule().Resources["pipewright_project.sales"].Primary.ID
						checkID = state.RootModule().Resources["pipewright_check.amount"].Primary.ID
						return nil
					},
				),
			},
			// Each resource imports to what was applied.
			{ResourceName: "pipewright_project.sales", ImportState: true, ImportStateVerify: true},
			{ResourceName: "pipewright_recipe.shipped", ImportState: true, ImportStateVerify: true,
				ImportStateIdFunc: importID("pipewright_recipe.shipped"), ImportStateVerifyIgnore: []string{"yaml"}},
			{ResourceName: "pipewright_connection.warehouse", ImportState: true, ImportStateVerify: true,
				ImportStateIdFunc: importID("pipewright_connection.warehouse"), ImportStateVerifyIgnore: []string{"config", "secrets"}},
			{ResourceName: "pipewright_schedule.nightly", ImportState: true, ImportStateVerify: true,
				ImportStateIdFunc: importID("pipewright_schedule.nightly"), ImportStateVerifyIgnore: []string{"next_run_at"}},
			{ResourceName: "pipewright_check.amount", ImportState: true, ImportStateVerify: true,
				ImportStateIdFunc: importID("pipewright_check.amount")},
			{ResourceName: "pipewright_workflow.weekly", ImportState: true, ImportStateVerify: true,
				ImportStateIdFunc: importID("pipewright_workflow.weekly"), ImportStateVerifyIgnore: []string{"tasks", "links"}},
			// A change made in the app is seen, and put back.
			{
				PreConfig: func() {
					path := "/projects/" + projectID + "/data-quality/rules/" + checkID
					if err := testAPI(t).Do(context.Background(), "PATCH", path, map[string]any{"severity": "warning"}, nil); err != nil {
						t.Fatal(err)
					}
				},
				Config: everything(name, false),
				ConfigPlanChecks: resource.ConfigPlanChecks{PreApply: []plancheck.PlanCheck{
					plancheck.ExpectResourceAction("pipewright_check.amount", plancheck.ResourceActionUpdate),
				}},
				Check: resource.TestCheckResourceAttr("pipewright_check.amount", "severity", "error"),
			},
			// A changed recipe is saved as its next revision, in place.
			{
				Config: everything(name, true),
				ConfigPlanChecks: resource.ConfigPlanChecks{PreApply: []plancheck.PlanCheck{
					plancheck.ExpectResourceAction("pipewright_recipe.shipped", plancheck.ResourceActionUpdate),
				}},
				Check: resource.TestCheckResourceAttr("pipewright_recipe.shipped", "revision", "2"),
			},
		},
	})
}

func TestAccAMember(t *testing.T) {
	username := os.Getenv("PIPEWRIGHT_TEST_MEMBER")
	if username == "" {
		t.Skip("PIPEWRIGHT_TEST_MEMBER names an account to add as a member")
	}
	name := "Terraform members " + acctest.RandStringFromCharSet(8, acctest.CharSetAlphaNum)
	config := func(role string) string {
		return fmt.Sprintf(`
resource "pipewright_project" "team" { name = %q }
resource "pipewright_project_member" "someone" {
  project_id = pipewright_project.team.id
  username   = %q
  role       = %q
}`, name, username, role)
	}
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{Config: config("viewer"), Check: resource.TestCheckResourceAttr("pipewright_project_member.someone", "role", "viewer")},
			{Config: config("editor"), Check: resource.TestCheckResourceAttr("pipewright_project_member.someone", "role", "editor")},
			{ResourceName: "pipewright_project_member.someone", ImportState: true, ImportStateVerify: true,
				ImportStateIdFunc: importID("pipewright_project_member.someone")},
		},
	})
}
