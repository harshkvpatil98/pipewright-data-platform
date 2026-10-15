package provider

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/client"
)

// The value Pipewright shows for a secret it keeps.
const hiddenSecret = "***"

type connectionResource struct{ api *client.Client }

type connectionModel struct {
	ID            types.String `tfsdk:"id"`
	ProjectID     types.String `tfsdk:"project_id"`
	Name          types.String `tfsdk:"name"`
	ConnectorType types.String `tfsdk:"connector_type"`
	Description   types.String `tfsdk:"description"`
	Config        types.String `tfsdk:"config"`
	Secrets       types.String `tfsdk:"secrets"`
	Status        types.String `tfsdk:"status"`
}

type connectionAPI struct {
	ID            string         `json:"id"`
	Name          string         `json:"name"`
	ConnectorType string         `json:"connector_type"`
	Description   *string        `json:"description"`
	Status        string         `json:"status"`
	Config        map[string]any `json:"config_json"`
}

func newConnectionResource() resource.Resource { return &connectionResource{} }

func (r *connectionResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_connection"
}

func (r *connectionResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "A saved connection to a database or service, to import from. Its secrets are written, never " +
			"read back: Pipewright keeps them encrypted and shows them as ***.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{Computed: true, PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
			"project_id": schema.StringAttribute{Required: true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()}},
			"name": schema.StringAttribute{Required: true, Validators: []validator.String{stringvalidator.LengthBetween(2, 160)}},
			"connector_type": schema.StringAttribute{Required: true, Description: "Such as postgresql, mysql or stripe.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()}},
			"description": schema.StringAttribute{Optional: true},
			"config": schema.StringAttribute{Required: true,
				Description: "Its settings other than secrets, with jsonencode: host, port, database, username and so on."},
			"secrets": schema.StringAttribute{Optional: true, Sensitive: true,
				Description: "Its secrets, with jsonencode, such as {password = var.password}. Written, never read back; " +
					"a change here is sent on the next apply."},
			"status": schema.StringAttribute{Optional: true, Computed: true, Default: stringdefault.StaticString("active"),
				Validators: []validator.String{stringvalidator.OneOf("active", "disabled")}},
		},
	}
}

func (r *connectionResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (r *connectionResource) path(m connectionModel) string {
	return "/projects/" + m.ProjectID.ValueString() + "/extraction/connections"
}

// settings is the config sent: the settings and the secrets together.
func (m connectionModel) settings() (map[string]any, error) {
	config := map[string]any{}
	if err := decodeJSON(m.Config.ValueString(), &config); err != nil {
		return nil, err
	}
	if !m.Secrets.IsNull() && !m.Secrets.IsUnknown() {
		secrets := map[string]any{}
		if err := decodeJSON(m.Secrets.ValueString(), &secrets); err != nil {
			return nil, err
		}
		for key, value := range secrets {
			config[key] = value
		}
	}
	return config, nil
}

// from reads a connection back; config keeps to the settings this configuration
// names, so defaults the server filled in and secrets (***) are not a change.
func (m *connectionModel) from(found connectionAPI) {
	m.ID = types.StringValue(found.ID)
	m.Name = types.StringValue(found.Name)
	m.ConnectorType = types.StringValue(found.ConnectorType)
	m.Description = stringOrNull(found.Description)
	m.Status = types.StringValue(found.Status)
	ours := map[string]any{}
	if decodeJSON(m.Config.ValueString(), &ours) == nil {
		server := map[string]any{}
		for key, value := range found.Config {
			if value != hiddenSecret {
				server[key] = value
			}
		}
		kept := onlyKeys(server, ours)
		if !sameJSON(kept, ours) {
			m.Config = types.StringValue(encodeJSON(kept))
		}
	}
}

func (r *connectionResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan connectionModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	config, err := plan.settings()
	if err != nil {
		resp.Diagnostics.AddError("The connection's settings are not right", err.Error())
		return
	}
	var made connectionAPI
	body := map[string]any{"name": plan.Name.ValueString(), "connector_type": plan.ConnectorType.ValueString(),
		"description": optionalString(plan.Description), "config": config}
	if err := r.api.Do(ctx, "POST", r.path(plan), body, &made); err != nil {
		refused(&resp.Diagnostics, "make the connection", err)
		return
	}
	if plan.Status.ValueString() != made.Status {
		if err := r.api.Do(ctx, "PATCH", r.path(plan)+"/"+made.ID, map[string]any{"status": plan.Status.ValueString()}, &made); err != nil {
			refused(&resp.Diagnostics, "set the connection's status", err)
			return
		}
	}
	plan.from(made)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *connectionResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state connectionModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var found connectionAPI
	if err := r.api.Do(ctx, "GET", r.path(state)+"/"+state.ID.ValueString(), nil, &found); err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		refused(&resp.Diagnostics, "read the connection", err)
		return
	}
	if state.Config.IsNull() || state.Config.ValueString() == "" {
		// Imported: every setting but the secrets is managed from here on.
		settings := map[string]any{}
		for key, value := range found.Config {
			if value != hiddenSecret {
				settings[key] = value
			}
		}
		state.Config = types.StringValue(encodeJSON(settings))
	}
	state.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *connectionResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state connectionModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	config, err := plan.settings()
	if err != nil {
		resp.Diagnostics.AddError("The connection's settings are not right", err.Error())
		return
	}
	var found connectionAPI
	body := map[string]any{"name": plan.Name.ValueString(), "description": optionalString(plan.Description),
		"status": plan.Status.ValueString(), "config": config}
	if err := r.api.Do(ctx, "PATCH", r.path(state)+"/"+state.ID.ValueString(), body, &found); err != nil {
		refused(&resp.Diagnostics, "change the connection", err)
		return
	}
	plan.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *connectionResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state connectionModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	err := r.api.Do(ctx, "DELETE", r.path(state)+"/"+state.ID.ValueString(), nil, nil)
	if err != nil && !client.IsNotFound(err) {
		refused(&resp.Diagnostics, "delete the connection", err)
	}
}

func (r *connectionResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	importTwo(ctx, req, resp)
}
