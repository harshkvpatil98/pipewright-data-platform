package provider

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/client"
)

type checkResource struct{ api *client.Client }

type checkModel struct {
	ID          types.String `tfsdk:"id"`
	ProjectID   types.String `tfsdk:"project_id"`
	DatasetID   types.String `tfsdk:"dataset_id"`
	Name        types.String `tfsdk:"name"`
	Description types.String `tfsdk:"description"`
	RuleType    types.String `tfsdk:"rule_type"`
	Severity    types.String `tfsdk:"severity"`
	Config      types.String `tfsdk:"config"`
	Enabled     types.Bool   `tfsdk:"enabled"`
}

type checkAPI struct {
	ID          string         `json:"id"`
	DatasetID   *string        `json:"dataset_id"`
	Name        string         `json:"name"`
	Description *string        `json:"description"`
	RuleType    string         `json:"rule_type"`
	Severity    string         `json:"severity"`
	Config      map[string]any `json:"config_json"`
	Enabled     bool           `json:"enabled"`
}

func newCheckResource() resource.Resource { return &checkResource{} }

func (r *checkResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_check"
}

func (r *checkResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	replace := []planmodifier.String{stringplanmodifier.RequiresReplace()}
	resp.Schema = schema.Schema{
		Description: "A check: a rule a dataset's data must pass, such as every order having an email.",
		Attributes: map[string]schema.Attribute{
			"id":         schema.StringAttribute{Computed: true, PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
			"project_id": schema.StringAttribute{Required: true, PlanModifiers: replace},
			"dataset_id": schema.StringAttribute{Optional: true, PlanModifiers: replace,
				Description: "The dataset it checks; unset, every dataset in the project."},
			"name":        schema.StringAttribute{Required: true, Validators: []validator.String{stringvalidator.LengthBetween(2, 160)}},
			"description": schema.StringAttribute{Optional: true},
			"rule_type": schema.StringAttribute{Required: true, PlanModifiers: replace,
				Validators: []validator.String{stringvalidator.OneOf("not_null", "unique", "allowed_values", "range",
					"regex_match", "expression", "row_count", "freshness")}},
			"severity": schema.StringAttribute{Optional: true, Computed: true, Default: stringdefault.StaticString("error"),
				Validators: []validator.String{stringvalidator.OneOf("error", "warning")}},
			"config": schema.StringAttribute{Required: true,
				Description: "Its settings, with jsonencode, such as {column = \"email\"}."},
			"enabled": schema.BoolAttribute{Optional: true, Computed: true, Default: booldefault.StaticBool(true)},
		},
	}
}

func (r *checkResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (r *checkResource) path(m checkModel) string {
	return "/projects/" + m.ProjectID.ValueString() + "/data-quality/rules"
}

func (m *checkModel) from(found checkAPI) {
	m.ID = types.StringValue(found.ID)
	m.DatasetID = stringOrNull(found.DatasetID)
	m.Name = types.StringValue(found.Name)
	m.Description = stringOrNull(found.Description)
	m.RuleType = types.StringValue(found.RuleType)
	m.Severity = types.StringValue(found.Severity)
	m.Enabled = types.BoolValue(found.Enabled)
	ours := map[string]any{}
	if m.Config.IsNull() || decodeJSON(m.Config.ValueString(), &ours) != nil || !sameJSON(found.Config, ours) {
		m.Config = types.StringValue(encodeJSON(found.Config))
	}
}

func (r *checkResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan checkModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	config := map[string]any{}
	if err := decodeJSON(plan.Config.ValueString(), &config); err != nil {
		resp.Diagnostics.AddError("The check's config is not right", err.Error())
		return
	}
	body := map[string]any{"name": plan.Name.ValueString(), "description": optionalString(plan.Description),
		"rule_type": plan.RuleType.ValueString(), "severity": plan.Severity.ValueString(),
		"dataset_id": optionalString(plan.DatasetID), "config": config}
	var made checkAPI
	if err := r.api.Do(ctx, "POST", r.path(plan), body, &made); err != nil {
		refused(&resp.Diagnostics, "make the check", err)
		return
	}
	if !plan.Enabled.ValueBool() {
		if err := r.api.Do(ctx, "PATCH", r.path(plan)+"/"+made.ID, map[string]any{"enabled": false}, &made); err != nil {
			refused(&resp.Diagnostics, "turn the check off", err)
			return
		}
	}
	plan.from(made)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *checkResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state checkModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var found checkAPI
	if err := r.api.Do(ctx, "GET", r.path(state)+"/"+state.ID.ValueString(), nil, &found); err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		refused(&resp.Diagnostics, "read the check", err)
		return
	}
	state.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *checkResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state checkModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	config := map[string]any{}
	if err := decodeJSON(plan.Config.ValueString(), &config); err != nil {
		resp.Diagnostics.AddError("The check's config is not right", err.Error())
		return
	}
	body := map[string]any{"name": plan.Name.ValueString(), "description": optionalString(plan.Description),
		"severity": plan.Severity.ValueString(), "config": config, "enabled": plan.Enabled.ValueBool()}
	var found checkAPI
	if err := r.api.Do(ctx, "PATCH", r.path(state)+"/"+state.ID.ValueString(), body, &found); err != nil {
		refused(&resp.Diagnostics, "change the check", err)
		return
	}
	plan.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *checkResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state checkModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	err := r.api.Do(ctx, "DELETE", r.path(state)+"/"+state.ID.ValueString(), nil, nil)
	if err != nil && !client.IsNotFound(err) {
		refused(&resp.Diagnostics, "delete the check", err)
	}
}

func (r *checkResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	importTwo(ctx, req, resp)
}
