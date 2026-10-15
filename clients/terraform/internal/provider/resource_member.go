package provider

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/client"
)

type memberResource struct{ api *client.Client }

type memberModel struct {
	ID        types.String `tfsdk:"id"`
	ProjectID types.String `tfsdk:"project_id"`
	Username  types.String `tfsdk:"username"`
	Role      types.String `tfsdk:"role"`
}

type memberAPI struct {
	ID       *string `json:"id"`
	Username string  `json:"username"`
	Role     string  `json:"role"`
	IsOwner  bool    `json:"is_owner"`
}

func newMemberResource() resource.Resource { return &memberResource{} }

func (r *memberResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_project_member"
}

func (r *memberResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Someone who can open a project, and what they may do there.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{Computed: true, Description: "The membership's id.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
			"project_id": schema.StringAttribute{Required: true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()}},
			"username": schema.StringAttribute{Required: true, Description: "Their account's username.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()}},
			"role": schema.StringAttribute{Required: true,
				Validators: []validator.String{stringvalidator.OneOf("viewer", "operator", "editor", "admin")}},
		},
	}
}

func (r *memberResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (r *memberResource) path(m memberModel) string {
	return "/projects/" + m.ProjectID.ValueString() + "/members"
}

func (r *memberResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan memberModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var made memberAPI
	body := map[string]any{"username": plan.Username.ValueString(), "role": plan.Role.ValueString()}
	if err := r.api.Do(ctx, "POST", r.path(plan), body, &made); err != nil {
		refused(&resp.Diagnostics, "add the member", err)
		return
	}
	if made.ID == nil {
		resp.Diagnostics.AddError("Could not add the member", "The project's owner is a member already, as its admin.")
		return
	}
	plan.ID = types.StringValue(*made.ID)
	plan.Role = types.StringValue(made.Role)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *memberResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state memberModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var listed struct {
		Items []memberAPI `json:"items"`
	}
	if err := r.api.Do(ctx, "GET", r.path(state), nil, &listed); err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		refused(&resp.Diagnostics, "read the members", err)
		return
	}
	for _, member := range listed.Items {
		if member.ID != nil && *member.ID == state.ID.ValueString() {
			state.Username = types.StringValue(member.Username)
			state.Role = types.StringValue(member.Role)
			resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
			return
		}
	}
	resp.State.RemoveResource(ctx)
}

func (r *memberResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state memberModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var found memberAPI
	err := r.api.Do(ctx, "PATCH", r.path(state)+"/"+state.ID.ValueString(), map[string]any{"role": plan.Role.ValueString()}, &found)
	if err != nil {
		refused(&resp.Diagnostics, "change the member's role", err)
		return
	}
	plan.ID = state.ID
	plan.Role = types.StringValue(found.Role)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *memberResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state memberModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	err := r.api.Do(ctx, "DELETE", r.path(state)+"/"+state.ID.ValueString(), nil, nil)
	if err != nil && !client.IsNotFound(err) {
		refused(&resp.Diagnostics, "remove the member", err)
	}
}

func (r *memberResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	importTwo(ctx, req, resp)
}
