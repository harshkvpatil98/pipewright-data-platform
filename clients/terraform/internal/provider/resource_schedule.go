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

type scheduleResource struct{ api *client.Client }

type scheduleModel struct {
	ID           types.String `tfsdk:"id"`
	ProjectID    types.String `tfsdk:"project_id"`
	Name         types.String `tfsdk:"name"`
	Description  types.String `tfsdk:"description"`
	ScheduleType types.String `tfsdk:"schedule_type"`
	Cron         types.String `tfsdk:"cron_expression"`
	Timezone     types.String `tfsdk:"timezone"`
	Enabled      types.Bool   `tfsdk:"enabled"`
	Target       types.String `tfsdk:"target"`
	NextRunAt    types.String `tfsdk:"next_run_at"`
}

type scheduleAPI struct {
	ID           string         `json:"id"`
	Name         string         `json:"name"`
	Description  *string        `json:"description"`
	ScheduleType string         `json:"schedule_type"`
	Cron         string         `json:"cron_expression"`
	Timezone     *string        `json:"timezone"`
	Enabled      bool           `json:"enabled"`
	Target       map[string]any `json:"target_config_json"`
	NextRunAt    *string        `json:"next_run_at"`
}

func newScheduleResource() resource.Resource { return &scheduleResource{} }

func (r *scheduleResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_schedule"
}

func (r *scheduleResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "When something runs by itself: a recipe, a delivery to PostgreSQL, or a watch for schema changes.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{Computed: true, PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
			"project_id": schema.StringAttribute{Required: true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()}},
			"name":        schema.StringAttribute{Required: true},
			"description": schema.StringAttribute{Optional: true},
			"schedule_type": schema.StringAttribute{Optional: true, Computed: true,
				Default:       stringdefault.StaticString("transformation_pipeline_run"),
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()},
				Validators: []validator.String{stringvalidator.OneOf("transformation_pipeline_run", "postgres_publish",
					"connector_schema_watch")}},
			"cron_expression": schema.StringAttribute{Required: true, Description: "Five fields, such as 0 2 * * *."},
			"timezone":        schema.StringAttribute{Optional: true, Description: "Such as Europe/London; UTC when unset."},
			"enabled":         schema.BoolAttribute{Optional: true, Computed: true, Default: booldefault.StaticBool(true)},
			"target": schema.StringAttribute{Required: true,
				Description: "What it runs, with jsonencode: {pipeline_id = pipewright_recipe.x.id} for a recipe."},
			"next_run_at": schema.StringAttribute{Computed: true},
		},
	}
}

func (r *scheduleResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (r *scheduleResource) path(m scheduleModel) string {
	return "/projects/" + m.ProjectID.ValueString() + "/schedules"
}

func (m *scheduleModel) from(found scheduleAPI) {
	m.ID = types.StringValue(found.ID)
	m.Name = types.StringValue(found.Name)
	m.Description = stringOrNull(found.Description)
	m.ScheduleType = types.StringValue(found.ScheduleType)
	m.Cron = types.StringValue(found.Cron)
	// Unset here and UTC there is the same schedule.
	if found.Timezone == nil || *found.Timezone == "" || (m.Timezone.IsNull() && *found.Timezone == "UTC") {
		m.Timezone = types.StringNull()
	} else {
		m.Timezone = types.StringValue(*found.Timezone)
	}
	m.Enabled = types.BoolValue(found.Enabled)
	m.NextRunAt = stringOrNull(found.NextRunAt)
	ours := map[string]any{}
	if m.Target.IsNull() || decodeJSON(m.Target.ValueString(), &ours) != nil || !sameJSON(onlyKeys(found.Target, ours), ours) {
		m.Target = types.StringValue(encodeJSON(found.Target))
	}
}

func (m scheduleModel) body() (map[string]any, error) {
	target := map[string]any{}
	if err := decodeJSON(m.Target.ValueString(), &target); err != nil {
		return nil, err
	}
	body := map[string]any{"name": m.Name.ValueString(), "description": optionalString(m.Description),
		"cron_expression": m.Cron.ValueString(), "enabled": m.Enabled.ValueBool(), "target_config": target}
	if m.Timezone.IsNull() {
		body["timezone"] = ""
	} else {
		body["timezone"] = m.Timezone.ValueString()
	}
	return body, nil
}

func (r *scheduleResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan scheduleModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	body, err := plan.body()
	if err != nil {
		resp.Diagnostics.AddError("The schedule's target is not right", err.Error())
		return
	}
	body["schedule_type"] = plan.ScheduleType.ValueString()
	if plan.Timezone.IsNull() {
		delete(body, "timezone")
	}
	var made scheduleAPI
	if err := r.api.Do(ctx, "POST", r.path(plan), body, &made); err != nil {
		refused(&resp.Diagnostics, "make the schedule", err)
		return
	}
	plan.from(made)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *scheduleResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state scheduleModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var found scheduleAPI
	if err := r.api.Do(ctx, "GET", r.path(state)+"/"+state.ID.ValueString(), nil, &found); err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		refused(&resp.Diagnostics, "read the schedule", err)
		return
	}
	state.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *scheduleResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state scheduleModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	body, err := plan.body()
	if err != nil {
		resp.Diagnostics.AddError("The schedule's target is not right", err.Error())
		return
	}
	var found scheduleAPI
	if err := r.api.Do(ctx, "PATCH", r.path(state)+"/"+state.ID.ValueString(), body, &found); err != nil {
		refused(&resp.Diagnostics, "change the schedule", err)
		return
	}
	plan.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *scheduleResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state scheduleModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	err := r.api.Do(ctx, "DELETE", r.path(state)+"/"+state.ID.ValueString(), nil, nil)
	if err != nil && !client.IsNotFound(err) {
		refused(&resp.Diagnostics, "delete the schedule", err)
	}
}

func (r *scheduleResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	importTwo(ctx, req, resp)
}
