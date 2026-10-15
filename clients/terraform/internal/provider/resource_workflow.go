package provider

import (
	"context"
	"sort"

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

type workflowResource struct{ api *client.Client }

type workflowModel struct {
	ID          types.String `tfsdk:"id"`
	ProjectID   types.String `tfsdk:"project_id"`
	Name        types.String `tfsdk:"name"`
	Description types.String `tfsdk:"description"`
	TriggerType types.String `tfsdk:"trigger_type"`
	Cron        types.String `tfsdk:"cron_expression"`
	Timezone    types.String `tfsdk:"timezone"`
	Enabled     types.Bool   `tfsdk:"enabled"`
	Tasks       types.String `tfsdk:"tasks"`
	Links       types.String `tfsdk:"links"`
}

type workflowAPI struct {
	ID          string           `json:"id"`
	Name        string           `json:"name"`
	Description *string          `json:"description"`
	TriggerType string           `json:"trigger_type"`
	Cron        *string          `json:"cron_expression"`
	Timezone    *string          `json:"timezone"`
	Enabled     bool             `json:"enabled"`
	Nodes       []map[string]any `json:"nodes"`
	Edges       []map[string]any `json:"edges"`
}

// What a task and a link are, with the defaults the API fills in, so a task
// written without them is the same task.
var taskDefaults = map[string]any{"config": map[string]any{}, "continue_on_failure": false, "retries": 0,
	"retry_delay_seconds": 30}
var taskKeys = []string{"node_key", "name", "node_type", "config", "continue_on_failure", "retries", "retry_delay_seconds"}
var linkKeys = []string{"from_node_key", "to_node_key", "condition"}

func normalTasks(items []map[string]any) []map[string]any {
	out := make([]map[string]any, 0, len(items))
	for _, item := range items {
		task := map[string]any{}
		if settings, ok := item["config_json"]; ok && item["config"] == nil {
			item = mapWith(item, "config", settings) // as the API reads a task back
		}
		for _, key := range taskKeys {
			if value, ok := item[key]; ok && value != nil {
				task[key] = value
			} else if fallback, ok := taskDefaults[key]; ok {
				task[key] = fallback
			}
		}
		out = append(out, task)
	}
	sort.Slice(out, func(i, j int) bool { return asString(out[i]["node_key"]) < asString(out[j]["node_key"]) })
	return out
}

func normalLinks(items []map[string]any) []map[string]any {
	out := make([]map[string]any, 0, len(items))
	for _, item := range items {
		link := map[string]any{"condition": "on_success"}
		for _, key := range linkKeys {
			if value, ok := item[key]; ok && value != nil {
				link[key] = value
			}
		}
		out = append(out, link)
	}
	sort.Slice(out, func(i, j int) bool {
		return asString(out[i]["from_node_key"])+">"+asString(out[i]["to_node_key"]) <
			asString(out[j]["from_node_key"])+">"+asString(out[j]["to_node_key"])
	})
	return out
}

func mapWith(item map[string]any, key string, value any) map[string]any {
	out := make(map[string]any, len(item)+1)
	for k, v := range item {
		out[k] = v
	}
	out[key] = value
	return out
}

func asString(value any) string {
	text, _ := value.(string)
	return text
}

func newWorkflowResource() resource.Resource { return &workflowResource{} }

func (r *workflowResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_workflow"
}

func (r *workflowResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "A workflow: tasks that run in order, by hand or on a schedule.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{Computed: true, PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
			"project_id": schema.StringAttribute{Required: true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()}},
			"name":        schema.StringAttribute{Required: true, Validators: []validator.String{stringvalidator.LengthBetween(2, 160)}},
			"description": schema.StringAttribute{Optional: true},
			"trigger_type": schema.StringAttribute{Optional: true, Computed: true, Default: stringdefault.StaticString("manual"),
				Validators: []validator.String{stringvalidator.OneOf("manual", "cron")}},
			"cron_expression": schema.StringAttribute{Optional: true, Description: "For trigger_type cron."},
			"timezone":        schema.StringAttribute{Optional: true},
			"enabled":         schema.BoolAttribute{Optional: true, Computed: true, Default: booldefault.StaticBool(true)},
			"tasks": schema.StringAttribute{Required: true,
				Description: "Its tasks, with jsonencode: a list of {node_key, name, node_type, config}, such as " +
					"{node_key = \"clean\", name = \"Clean\", node_type = \"transformation\", config = {pipeline_id = ...}}."},
			"links": schema.StringAttribute{Optional: true, Computed: true, Default: stringdefault.StaticString("[]"),
				Description: "Which task follows which, with jsonencode: a list of {from_node_key, to_node_key, condition}."},
		},
	}
}

func (r *workflowResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (r *workflowResource) path(m workflowModel) string {
	return "/projects/" + m.ProjectID.ValueString() + "/workflows"
}

func (m workflowModel) body() (map[string]any, error) {
	var tasks, links []map[string]any
	if err := decodeJSON(m.Tasks.ValueString(), &tasks); err != nil {
		return nil, err
	}
	if err := decodeJSON(m.Links.ValueString(), &links); err != nil {
		return nil, err
	}
	if links == nil {
		links = []map[string]any{}
	}
	return map[string]any{"name": m.Name.ValueString(), "description": optionalString(m.Description),
		"trigger_type": m.TriggerType.ValueString(), "cron_expression": optionalString(m.Cron),
		"timezone": optionalString(m.Timezone), "nodes": tasks, "edges": links}, nil
}

func (m *workflowModel) from(found workflowAPI) {
	m.ID = types.StringValue(found.ID)
	m.Name = types.StringValue(found.Name)
	m.Description = stringOrNull(found.Description)
	m.TriggerType = types.StringValue(found.TriggerType)
	m.Cron = stringOrNull(found.Cron)
	if found.Timezone == nil || *found.Timezone == "" || (m.Timezone.IsNull() && *found.Timezone == "UTC") {
		m.Timezone = types.StringNull()
	} else {
		m.Timezone = types.StringValue(*found.Timezone)
	}
	m.Enabled = types.BoolValue(found.Enabled)
	server := normalTasks(found.Nodes)
	var ours []map[string]any
	if m.Tasks.IsNull() || decodeJSON(m.Tasks.ValueString(), &ours) != nil || !sameJSON(normalTasks(ours), server) {
		m.Tasks = types.StringValue(encodeJSON(server))
	}
	serverLinks := normalLinks(found.Edges)
	var ourLinks []map[string]any
	if m.Links.IsNull() || decodeJSON(m.Links.ValueString(), &ourLinks) != nil || !sameJSON(normalLinks(ourLinks), serverLinks) {
		m.Links = types.StringValue(encodeJSON(serverLinks))
	}
}

func (r *workflowResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan workflowModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	body, err := plan.body()
	if err != nil {
		resp.Diagnostics.AddError("The workflow's tasks are not right", err.Error())
		return
	}
	var made workflowAPI
	if err := r.api.Do(ctx, "POST", r.path(plan), body, &made); err != nil {
		refused(&resp.Diagnostics, "make the workflow", err)
		return
	}
	if !plan.Enabled.ValueBool() {
		if err := r.api.Do(ctx, "PATCH", r.path(plan)+"/"+made.ID, map[string]any{"enabled": false}, &made); err != nil {
			refused(&resp.Diagnostics, "turn the workflow off", err)
			return
		}
	}
	plan.from(made)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *workflowResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state workflowModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var found workflowAPI
	if err := r.api.Do(ctx, "GET", r.path(state)+"/"+state.ID.ValueString(), nil, &found); err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		refused(&resp.Diagnostics, "read the workflow", err)
		return
	}
	state.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *workflowResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state workflowModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	body, err := plan.body()
	if err != nil {
		resp.Diagnostics.AddError("The workflow's tasks are not right", err.Error())
		return
	}
	body["enabled"] = plan.Enabled.ValueBool()
	var found workflowAPI
	if err := r.api.Do(ctx, "PATCH", r.path(state)+"/"+state.ID.ValueString(), body, &found); err != nil {
		refused(&resp.Diagnostics, "change the workflow", err)
		return
	}
	plan.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *workflowResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state workflowModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	err := r.api.Do(ctx, "DELETE", r.path(state)+"/"+state.ID.ValueString(), nil, nil)
	if err != nil && !client.IsNotFound(err) {
		refused(&resp.Diagnostics, "delete the workflow", err)
	}
}

func (r *workflowResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	importTwo(ctx, req, resp)
}
