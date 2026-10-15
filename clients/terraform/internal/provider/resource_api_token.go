package provider

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework-validators/int64validator"
	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/int64planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/setplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/client"
)

type apiTokenResource struct{ api *client.Client }

type apiTokenModel struct {
	ID            types.String `tfsdk:"id"`
	Name          types.String `tfsdk:"name"`
	Scope         types.String `tfsdk:"scope"`
	ProjectIDs    types.Set    `tfsdk:"project_ids"`
	ExpiresInDays types.Int64  `tfsdk:"expires_in_days"`
	ExpiresAt     types.String `tfsdk:"expires_at"`
	Prefix        types.String `tfsdk:"prefix"`
	Secret        types.String `tfsdk:"secret"`
}

type apiTokenAPI struct {
	ID         string   `json:"id"`
	Name       string   `json:"name"`
	Scope      string   `json:"scope"`
	Prefix     string   `json:"prefix"`
	ProjectIDs []string `json:"project_ids"`
	ExpiresAt  *string  `json:"expires_at"`
	RevokedAt  *string  `json:"revoked_at"`
}

func newAPITokenResource() resource.Resource { return &apiTokenResource{} }

func (r *apiTokenResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_api_token"
}

func (r *apiTokenResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	replace := []planmodifier.String{stringplanmodifier.RequiresReplace()}
	keep := []planmodifier.String{stringplanmodifier.UseStateForUnknown()}
	resp.Schema = schema.Schema{
		Description: "An API token of the account this configuration signs in with, for a script or another system. " +
			"Any change makes a new token; destroying it revokes it.",
		Attributes: map[string]schema.Attribute{
			"id":   schema.StringAttribute{Computed: true, PlanModifiers: keep},
			"name": schema.StringAttribute{Required: true, PlanModifiers: replace},
			"scope": schema.StringAttribute{Required: true, PlanModifiers: replace,
				Validators: []validator.String{stringvalidator.OneOf("read", "write", "admin")}},
			"project_ids": schema.SetAttribute{Optional: true, ElementType: types.StringType,
				PlanModifiers: []planmodifier.Set{setplanmodifier.RequiresReplace()},
				Description:   "Only these projects; unset, every project the account can reach."},
			"expires_in_days": schema.Int64Attribute{Optional: true,
				PlanModifiers: []planmodifier.Int64{int64planmodifier.RequiresReplace()},
				Validators:    []validator.Int64{int64validator.Between(1, 3650)}},
			"expires_at": schema.StringAttribute{Computed: true, PlanModifiers: keep},
			"prefix":     schema.StringAttribute{Computed: true, PlanModifiers: keep},
			"secret": schema.StringAttribute{Computed: true, Sensitive: true, PlanModifiers: keep,
				Description: "The token itself, known only when it is made."},
		},
	}
}

func (r *apiTokenResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.api = configured(req.ProviderData, &resp.Diagnostics)
}

func (r *apiTokenResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan apiTokenModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	body := map[string]any{"name": plan.Name.ValueString(), "scope": plan.Scope.ValueString()}
	if !plan.ProjectIDs.IsNull() && !plan.ProjectIDs.IsUnknown() {
		var projects []string
		resp.Diagnostics.Append(plan.ProjectIDs.ElementsAs(ctx, &projects, false)...)
		body["project_ids"] = projects
	}
	if !plan.ExpiresInDays.IsNull() && !plan.ExpiresInDays.IsUnknown() {
		body["expires_in_days"] = plan.ExpiresInDays.ValueInt64()
	}
	var made struct {
		Token  apiTokenAPI `json:"token"`
		Secret string      `json:"secret"`
	}
	if err := r.api.Do(ctx, "POST", "/auth/tokens", body, &made); err != nil {
		refused(&resp.Diagnostics, "make the API token", err)
		return
	}
	plan.ID = types.StringValue(made.Token.ID)
	plan.Prefix = types.StringValue(made.Token.Prefix)
	plan.ExpiresAt = stringOrNull(made.Token.ExpiresAt)
	plan.Secret = types.StringValue(made.Secret)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *apiTokenResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state apiTokenModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var found apiTokenAPI
	if err := r.api.Do(ctx, "GET", "/auth/tokens/"+state.ID.ValueString(), nil, &found); err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		refused(&resp.Diagnostics, "read the API token", err)
		return
	}
	if found.RevokedAt != nil {
		resp.State.RemoveResource(ctx) // revoked in the app: Terraform makes a new one
		return
	}
	state.Name = types.StringValue(found.Name)
	state.Scope = types.StringValue(found.Scope)
	state.Prefix = types.StringValue(found.Prefix)
	state.ExpiresAt = stringOrNull(found.ExpiresAt)
	if len(found.ProjectIDs) > 0 {
		values := make([]attr.Value, 0, len(found.ProjectIDs))
		for _, id := range found.ProjectIDs {
			values = append(values, types.StringValue(id))
		}
		set, diags := types.SetValue(types.StringType, values)
		resp.Diagnostics.Append(diags...)
		state.ProjectIDs = set
	} else {
		state.ProjectIDs = types.SetNull(types.StringType)
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

// Update is never asked for: every setting makes a new token.
func (r *apiTokenResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan apiTokenModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *apiTokenResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state apiTokenModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	err := r.api.Do(ctx, "DELETE", "/auth/tokens/"+state.ID.ValueString(), nil, nil)
	if err != nil && !client.IsNotFound(err) {
		refused(&resp.Diagnostics, "revoke the API token", err)
	}
}
