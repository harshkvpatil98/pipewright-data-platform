package provider

import (
	"context"
	"fmt"

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

type projectResource struct{ api *client.Client }

type projectModel struct {
	ID               types.String `tfsdk:"id"`
	Name             types.String `tfsdk:"name"`
	Description      types.String `tfsdk:"description"`
	Status           types.String `tfsdk:"status"`
	Slug             types.String `tfsdk:"slug"`
	RequiresApproval types.Bool   `tfsdk:"requires_approval"`
}

type projectAPI struct {
	ID               string  `json:"id"`
	Name             string  `json:"name"`
	Description      *string `json:"description"`
	Status           string  `json:"status"`
	Slug             string  `json:"slug"`
	RequiresApproval bool    `json:"requires_approval"`
}

func newProjectResource() resource.Resource { return &projectResource{} }

func (r *projectResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_project"
}

func (r *projectResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "A project: a space for one team or subject, which everything else lives in.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{Computed: true, PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
			"name": schema.StringAttribute{Required: true, Description: "What people see.",
				Validators: []validator.String{stringvalidator.LengthBetween(2, 160)}},
			"description": schema.StringAttribute{Optional: true},
			"status": schema.StringAttribute{Optional: true, Computed: true, Default: stringdefault.StaticString("active"),
				Validators: []validator.String{stringvalidator.OneOf("active", "draft", "archived")}},
			"slug": schema.StringAttribute{Computed: true, Description: "Made from the name when the project is made.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
			"requires_approval": schema.BoolAttribute{Optional: true, Computed: true,
				Description: "Changes to recipes and workflows are suggested and approved, not saved directly."},
		},
	}
}

func (r *projectResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (m *projectModel) from(found projectAPI) {
	m.ID = types.StringValue(found.ID)
	m.Name = types.StringValue(found.Name)
	m.Description = stringOrNull(found.Description)
	m.Status = types.StringValue(found.Status)
	m.Slug = types.StringValue(found.Slug)
	m.RequiresApproval = types.BoolValue(found.RequiresApproval)
}

func (r *projectResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan projectModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var made projectAPI
	body := map[string]any{"name": plan.Name.ValueString(), "description": optionalString(plan.Description),
		"status": plan.Status.ValueString()}
	if err := r.api.Do(ctx, "POST", "/projects", body, &made); err != nil {
		refused(&resp.Diagnostics, "make the project", err)
		return
	}
	if !plan.RequiresApproval.IsNull() && !plan.RequiresApproval.IsUnknown() && plan.RequiresApproval.ValueBool() {
		if err := r.api.Do(ctx, "PATCH", "/projects/"+made.ID, map[string]any{"requires_approval": true}, &made); err != nil {
			refused(&resp.Diagnostics, "ask for approval on the project", err)
			return
		}
	}
	plan.from(made)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *projectResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state projectModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var found projectAPI
	if err := r.api.Do(ctx, "GET", "/projects/"+state.ID.ValueString(), nil, &found); err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		refused(&resp.Diagnostics, "read the project", err)
		return
	}
	state.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *projectResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state projectModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	body := map[string]any{"name": plan.Name.ValueString(), "description": optionalString(plan.Description),
		"status": plan.Status.ValueString()}
	if !plan.RequiresApproval.IsNull() && !plan.RequiresApproval.IsUnknown() {
		body["requires_approval"] = plan.RequiresApproval.ValueBool()
	}
	var found projectAPI
	if err := r.api.Do(ctx, "PATCH", "/projects/"+state.ID.ValueString(), body, &found); err != nil {
		refused(&resp.Diagnostics, "change the project", err)
		return
	}
	plan.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *projectResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state projectModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	if err := r.api.Do(ctx, "DELETE", "/projects/"+state.ID.ValueString(), nil, nil); err != nil && !client.IsNotFound(err) {
		refused(&resp.Diagnostics, fmt.Sprintf("delete the project %s", state.Name.ValueString()), err)
	}
}

func (r *projectResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, pathOf("id"), req.ID)...)
}
