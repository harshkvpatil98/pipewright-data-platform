// Package provider is Pipewright's Terraform provider: projects, members,
// connections, datasets from files, recipes, schedules, checks, workflows and
// API tokens as code, each read back so `terraform plan` shows what changed in
// the app since the last apply.
package provider

import (
	"context"
	"os"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/provider"
	"github.com/hashicorp/terraform-plugin-framework/provider/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/client"
)

var _ provider.Provider = &pipewrightProvider{}

type pipewrightProvider struct {
	version string
}

type providerModel struct {
	URL   types.String `tfsdk:"url"`
	Token types.String `tfsdk:"token"`
}

// New makes the provider, for the plugin server.
func New(version string) func() provider.Provider {
	return func() provider.Provider {
		return &pipewrightProvider{version: version}
	}
}

func (p *pipewrightProvider) Metadata(_ context.Context, _ provider.MetadataRequest, resp *provider.MetadataResponse) {
	resp.TypeName = "pipewright"
	resp.Version = p.version
}

func (p *pipewrightProvider) Schema(_ context.Context, _ provider.SchemaRequest, resp *provider.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Manage a Pipewright deployment as code.",
		Attributes: map[string]schema.Attribute{
			"url": schema.StringAttribute{
				Description: "Where Pipewright is, such as https://pipewright.example.com. Or set PIPEWRIGHT_URL.",
				Optional:    true,
			},
			"token": schema.StringAttribute{
				Description: "An API token from Your settings → API tokens (it starts with pw_), best limited to the " +
					"projects this configuration manages. Or set PIPEWRIGHT_TOKEN.",
				Optional:  true,
				Sensitive: true,
			},
		},
	}
}

func (p *pipewrightProvider) Configure(ctx context.Context, req provider.ConfigureRequest, resp *provider.ConfigureResponse) {
	var config providerModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}
	address := os.Getenv("PIPEWRIGHT_URL")
	if !config.URL.IsNull() && !config.URL.IsUnknown() {
		address = config.URL.ValueString()
	}
	token := os.Getenv("PIPEWRIGHT_TOKEN")
	if !config.Token.IsNull() && !config.Token.IsUnknown() {
		token = config.Token.ValueString()
	}
	api, err := client.New(address, token)
	if err != nil {
		resp.Diagnostics.AddError("Pipewright is not set up", err.Error())
		return
	}
	resp.ResourceData = api
	resp.DataSourceData = api
}

func (p *pipewrightProvider) Resources(_ context.Context) []func() resource.Resource {
	return []func() resource.Resource{
		newProjectResource,
		newMemberResource,
		newConnectionResource,
		newFileDatasetResource,
		newRecipeResource,
		newScheduleResource,
		newCheckResource,
		newWorkflowResource,
		newAPITokenResource,
	}
}

func (p *pipewrightProvider) DataSources(_ context.Context) []func() datasource.DataSource {
	return []func() datasource.DataSource{
		newProjectDataSource,
		newDatasetDataSource,
		newConnectionDataSource,
	}
}
