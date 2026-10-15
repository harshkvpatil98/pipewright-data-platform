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

type recipeResource struct{ api *client.Client }

type recipeModel struct {
	ID          types.String `tfsdk:"id"`
	ProjectID   types.String `tfsdk:"project_id"`
	DatasetID   types.String `tfsdk:"dataset_id"`
	Name        types.String `tfsdk:"name"`
	Description types.String `tfsdk:"description"`
	YAML        types.String `tfsdk:"yaml"`
	Revision    types.Int64  `tfsdk:"revision"`
	OutputID    types.String `tfsdk:"output_dataset_id"`
}

type recipeAPI struct {
	ID              string           `json:"id"`
	BaseDatasetID   string           `json:"base_dataset_id"`
	Name            string           `json:"name"`
	Description     *string          `json:"description"`
	Steps           []map[string]any `json:"steps_json"`
	Revision        int64            `json:"revision"`
	OutputDatasetID *string          `json:"output_dataset_id"`
}

func newRecipeResource() resource.Resource { return &recipeResource{} }

func (r *recipeResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_recipe"
}

func (r *recipeResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "A recipe: steps that turn one dataset into another, written as recipe YAML (the file the Studio " +
			"shows under Details → File). Compared by its steps, so spacing and order of keys are never a change.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{Computed: true, PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
			"project_id": schema.StringAttribute{Required: true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()}},
			"dataset_id": schema.StringAttribute{Required: true, Description: "The dataset it reads.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()}},
			"name":        schema.StringAttribute{Required: true, Validators: []validator.String{stringvalidator.LengthBetween(2, 160)}},
			"description": schema.StringAttribute{Optional: true},
			"yaml": schema.StringAttribute{Required: true,
				Description:   "The recipe as YAML: version, steps. A step's name is its note.",
				PlanModifiers: []planmodifier.String{sameStepsModifier{r}}},
			// Rises with every save, so it is known only after one.
			"revision": schema.Int64Attribute{Computed: true},
			"output_dataset_id": schema.StringAttribute{Computed: true, Description: "What its runs write, after the first.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
		},
	}
}

// sameStepsModifier keeps the YAML in the state when the planned YAML has the
// same steps, so reformatting it is not a change.
type sameStepsModifier struct{ r *recipeResource }

func (m sameStepsModifier) Description(context.Context) string {
	return "YAML with the same steps is the same recipe."
}

func (m sameStepsModifier) MarkdownDescription(ctx context.Context) string { return m.Description(ctx) }

func (m sameStepsModifier) PlanModifyString(ctx context.Context, req planmodifier.StringRequest, resp *planmodifier.StringResponse) {
	if m.r.api == nil || req.StateValue.IsNull() || req.PlanValue.IsUnknown() || req.PlanValue.IsNull() ||
		req.StateValue.ValueString() == req.PlanValue.ValueString() {
		return
	}
	planned, err := m.r.steps(ctx, req.PlanValue.ValueString())
	if err != nil {
		return // the apply reports it
	}
	stored, err := m.r.steps(ctx, req.StateValue.ValueString())
	if err == nil && sameJSON(planned, stored) {
		resp.PlanValue = req.StateValue
	}
}

func (r *recipeResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.api = configured(req.ProviderData, &resp.Diagnostics)
}

// steps reads recipe YAML through Pipewright's own reader.
func (r *recipeResource) steps(ctx context.Context, text string) ([]map[string]any, error) {
	var parsed struct {
		Steps []map[string]any `json:"steps"`
	}
	err := r.api.Do(ctx, "POST", "/workbench/recipe/parse", map[string]any{"yaml": text}, &parsed)
	return parsed.Steps, err
}

func (r *recipeResource) from(ctx context.Context, m *recipeModel, found recipeAPI) error {
	m.ID = types.StringValue(found.ID)
	m.DatasetID = types.StringValue(found.BaseDatasetID)
	m.Name = types.StringValue(found.Name)
	m.Description = stringOrNull(found.Description)
	m.Revision = types.Int64Value(found.Revision)
	m.OutputID = stringOrNull(found.OutputDatasetID)
	// The YAML written here stays while its steps are the recipe's; otherwise the
	// recipe's own steps, as YAML, show what changed in the app.
	if !m.YAML.IsNull() && !m.YAML.IsUnknown() {
		ours, err := r.steps(ctx, m.YAML.ValueString())
		if err == nil && sameJSON(ours, found.Steps) {
			return nil
		}
	}
	var written struct {
		YAML string `json:"yaml"`
	}
	if err := r.api.Do(ctx, "POST", "/workbench/recipe/yaml", map[string]any{"steps": found.Steps}, &written); err != nil {
		return err
	}
	m.YAML = types.StringValue(written.YAML)
	return nil
}

func (r *recipeResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan recipeModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	steps, err := r.steps(ctx, plan.YAML.ValueString())
	if err != nil {
		refused(&resp.Diagnostics, "read the recipe's YAML", err)
		return
	}
	var made recipeAPI
	body := map[string]any{"name": plan.Name.ValueString(), "description": optionalString(plan.Description),
		"steps_json": steps}
	path := "/projects/" + plan.ProjectID.ValueString() + "/datasets/" + plan.DatasetID.ValueString() + "/pipelines"
	if err := r.api.Do(ctx, "POST", path, body, &made); err != nil {
		refused(&resp.Diagnostics, "make the recipe", err)
		return
	}
	if err := r.from(ctx, &plan, made); err != nil {
		refused(&resp.Diagnostics, "read the recipe back", err)
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *recipeResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state recipeModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var found recipeAPI
	err := r.api.Do(ctx, "GET", "/projects/"+state.ProjectID.ValueString()+"/pipelines/"+state.ID.ValueString(), nil, &found)
	if err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		refused(&resp.Diagnostics, "read the recipe", err)
		return
	}
	if err := r.from(ctx, &state, found); err != nil {
		refused(&resp.Diagnostics, "write the recipe as YAML", err)
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *recipeResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state recipeModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	steps, err := r.steps(ctx, plan.YAML.ValueString())
	if err != nil {
		refused(&resp.Diagnostics, "read the recipe's YAML", err)
		return
	}
	// Naming the revision this plan read means a save in the app since is not
	// written over: the apply stops, and a refresh shows it.
	body := map[string]any{"name": plan.Name.ValueString(), "description": optionalString(plan.Description),
		"steps_json": steps, "expected_revision": state.Revision.ValueInt64()}
	var found recipeAPI
	if err := r.api.Do(ctx, "PATCH", "/projects/"+state.ProjectID.ValueString()+"/pipelines/"+state.ID.ValueString(), body, &found); err != nil {
		refused(&resp.Diagnostics, "change the recipe", err)
		return
	}
	if err := r.from(ctx, &plan, found); err != nil {
		refused(&resp.Diagnostics, "read the recipe back", err)
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *recipeResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state recipeModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	err := r.api.Do(ctx, "DELETE", "/projects/"+state.ProjectID.ValueString()+"/pipelines/"+state.ID.ValueString(), nil, nil)
	if err != nil && !client.IsNotFound(err) {
		refused(&resp.Diagnostics, "delete the recipe", err)
	}
}

func (r *recipeResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	importTwo(ctx, req, resp)
}
