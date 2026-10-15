package provider

import (
	"context"
	"fmt"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/client"
)

// ---------------------------------------------------------------- a project

type projectDataSource struct{ api *client.Client }

type projectDataModel struct {
	ID          types.String `tfsdk:"id"`
	Name        types.String `tfsdk:"name"`
	Slug        types.String `tfsdk:"slug"`
	Description types.String `tfsdk:"description"`
}

func newProjectDataSource() datasource.DataSource { return &projectDataSource{} }

func (d *projectDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_project"
}

func (d *projectDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "A project this configuration does not manage, by its id or its name.",
		Attributes: map[string]schema.Attribute{
			"id":          schema.StringAttribute{Optional: true, Computed: true},
			"name":        schema.StringAttribute{Optional: true, Computed: true},
			"slug":        schema.StringAttribute{Computed: true},
			"description": schema.StringAttribute{Computed: true},
		},
	}
}

func (d *projectDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	d.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (d *projectDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var config projectDataModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var listed struct {
		Items []projectAPI `json:"items"`
	}
	if err := d.api.Do(ctx, "GET", "/projects", nil, &listed); err != nil {
		refused(&resp.Diagnostics, "list the projects", err)
		return
	}
	for _, item := range listed.Items {
		if item.ID == config.ID.ValueString() || (config.ID.IsNull() && item.Name == config.Name.ValueString()) {
			config.ID, config.Name, config.Slug = types.StringValue(item.ID), types.StringValue(item.Name), types.StringValue(item.Slug)
			config.Description = stringOrNull(item.Description)
			resp.Diagnostics.Append(resp.State.Set(ctx, config)...)
			return
		}
	}
	resp.Diagnostics.AddError("No such project", fmt.Sprintf("No project you can reach has the id %q or the name %q.",
		config.ID.ValueString(), config.Name.ValueString()))
}

// ---------------------------------------------------------------- a dataset

type datasetDataSource struct{ api *client.Client }

type datasetDataModel struct {
	ID          types.String `tfsdk:"id"`
	ProjectID   types.String `tfsdk:"project_id"`
	Name        types.String `tfsdk:"name"`
	RowCount    types.Int64  `tfsdk:"row_count"`
	ColumnCount types.Int64  `tfsdk:"column_count"`
}

func newDatasetDataSource() datasource.DataSource { return &datasetDataSource{} }

func (d *datasetDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_dataset"
}

func (d *datasetDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "A dataset in a project, by its id or its name: an import's or a recipe's result to build on.",
		Attributes: map[string]schema.Attribute{
			"id":           schema.StringAttribute{Optional: true, Computed: true},
			"project_id":   schema.StringAttribute{Required: true},
			"name":         schema.StringAttribute{Optional: true, Computed: true},
			"row_count":    schema.Int64Attribute{Computed: true},
			"column_count": schema.Int64Attribute{Computed: true},
		},
	}
}

func (d *datasetDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	d.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (d *datasetDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var config datasetDataModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var listed struct {
		Items []datasetAPI `json:"items"`
	}
	if err := d.api.Do(ctx, "GET", "/projects/"+config.ProjectID.ValueString()+"/datasets", nil, &listed); err != nil {
		refused(&resp.Diagnostics, "list the datasets", err)
		return
	}
	for _, item := range listed.Items {
		if item.ID == config.ID.ValueString() || (config.ID.IsNull() && item.Name == config.Name.ValueString()) {
			config.ID, config.Name = types.StringValue(item.ID), types.StringValue(item.Name)
			config.RowCount, config.ColumnCount = types.Int64Null(), types.Int64Null()
			if item.RowCount != nil {
				config.RowCount = types.Int64Value(*item.RowCount)
			}
			if item.ColumnCount != nil {
				config.ColumnCount = types.Int64Value(*item.ColumnCount)
			}
			resp.Diagnostics.Append(resp.State.Set(ctx, config)...)
			return
		}
	}
	resp.Diagnostics.AddError("No such dataset", fmt.Sprintf("The project has no dataset with the id %q or the name %q.",
		config.ID.ValueString(), config.Name.ValueString()))
}

// ---------------------------------------------------------------- a connection

type connectionDataSource struct{ api *client.Client }

type connectionDataModel struct {
	ID            types.String `tfsdk:"id"`
	ProjectID     types.String `tfsdk:"project_id"`
	Name          types.String `tfsdk:"name"`
	ConnectorType types.String `tfsdk:"connector_type"`
	Status        types.String `tfsdk:"status"`
}

func newConnectionDataSource() datasource.DataSource { return &connectionDataSource{} }

func (d *connectionDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_connection"
}

func (d *connectionDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "A saved connection in a project, by its name; its secrets never leave Pipewright.",
		Attributes: map[string]schema.Attribute{
			"id":             schema.StringAttribute{Computed: true},
			"project_id":     schema.StringAttribute{Required: true},
			"name":           schema.StringAttribute{Required: true},
			"connector_type": schema.StringAttribute{Computed: true},
			"status":         schema.StringAttribute{Computed: true},
		},
	}
}

func (d *connectionDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	d.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (d *connectionDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var config connectionDataModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var listed struct {
		Items []connectionAPI `json:"items"`
	}
	path := "/projects/" + config.ProjectID.ValueString() + "/extraction/connections"
	if err := d.api.Do(ctx, "GET", path, nil, &listed); err != nil {
		refused(&resp.Diagnostics, "list the connections", err)
		return
	}
	for _, item := range listed.Items {
		if item.Name == config.Name.ValueString() {
			config.ID = types.StringValue(item.ID)
			config.ConnectorType = types.StringValue(item.ConnectorType)
			config.Status = types.StringValue(item.Status)
			resp.Diagnostics.Append(resp.State.Set(ctx, config)...)
			return
		}
	}
	resp.Diagnostics.AddError("No such connection", fmt.Sprintf("The project has no connection called %q.", config.Name.ValueString()))
}
