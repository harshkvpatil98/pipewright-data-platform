package provider

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/int64planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/client"
)

type fileDatasetResource struct{ api *client.Client }

type fileDatasetModel struct {
	ID          types.String `tfsdk:"id"`
	ProjectID   types.String `tfsdk:"project_id"`
	Name        types.String `tfsdk:"name"`
	Source      types.String `tfsdk:"source"`
	SourceHash  types.String `tfsdk:"source_hash"`
	RowCount    types.Int64  `tfsdk:"row_count"`
	ColumnCount types.Int64  `tfsdk:"column_count"`
}

type datasetAPI struct {
	ID              string  `json:"id"`
	Name            string  `json:"name"`
	IngestionStatus *string `json:"ingestion_status"`
	IngestionError  *string `json:"ingestion_error"`
	RowCount        *int64  `json:"row_count"`
	ColumnCount     *int64  `json:"column_count"`
}

func newFileDatasetResource() resource.Resource { return &fileDatasetResource{} }

func (r *fileDatasetResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_file_dataset"
}

func (r *fileDatasetResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	replace := []planmodifier.String{stringplanmodifier.RequiresReplace()}
	resp.Schema = schema.Schema{
		Description: "A dataset uploaded from a file: CSV, Excel, JSON, Parquet and the rest Pipewright reads. A new " +
			"file (a new source_hash) uploads a new dataset in its place.",
		Attributes: map[string]schema.Attribute{
			"id":         schema.StringAttribute{Computed: true, PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()}},
			"project_id": schema.StringAttribute{Required: true, PlanModifiers: replace},
			"name":       schema.StringAttribute{Required: true, PlanModifiers: replace},
			"source":     schema.StringAttribute{Required: true, Description: "The file's path.", PlanModifiers: replace},
			"source_hash": schema.StringAttribute{Optional: true, PlanModifiers: replace,
				Description: "filesha256(source), so a changed file is uploaded again."},
			"row_count": schema.Int64Attribute{Computed: true,
				PlanModifiers: []planmodifier.Int64{int64planmodifier.UseStateForUnknown()}},
			"column_count": schema.Int64Attribute{Computed: true,
				PlanModifiers: []planmodifier.Int64{int64planmodifier.UseStateForUnknown()}},
		},
	}
}

func (r *fileDatasetResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.api = configured(req.ProviderData, &resp.Diagnostics)
}

func fileHash(source string) (string, error) {
	file, err := os.Open(source)
	if err != nil {
		return "", err
	}
	defer file.Close()
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

func (m *fileDatasetModel) from(found datasetAPI) {
	m.ID = types.StringValue(found.ID)
	m.Name = types.StringValue(found.Name)
	if found.RowCount != nil {
		m.RowCount = types.Int64Value(*found.RowCount)
	} else {
		m.RowCount = types.Int64Null()
	}
	if found.ColumnCount != nil {
		m.ColumnCount = types.Int64Value(*found.ColumnCount)
	} else {
		m.ColumnCount = types.Int64Null()
	}
}

func (r *fileDatasetResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan fileDatasetModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	if !plan.SourceHash.IsNull() && !plan.SourceHash.IsUnknown() {
		actual, err := fileHash(plan.Source.ValueString())
		if err != nil {
			resp.Diagnostics.AddError("Could not read the file", err.Error())
			return
		}
		if actual != plan.SourceHash.ValueString() {
			resp.Diagnostics.AddError("The file changed", fmt.Sprintf("%s has sha256 %s, not the source_hash given.",
				plan.Source.ValueString(), actual))
			return
		}
	}
	var made struct {
		Dataset datasetAPI `json:"dataset"`
	}
	if err := r.api.Upload(ctx, plan.ProjectID.ValueString(), plan.Name.ValueString(), plan.Source.ValueString(), &made); err != nil {
		refused(&resp.Diagnostics, "upload the file", err)
		return
	}
	// A large file is read in the background: wait until it is, up to ten minutes.
	found := made.Dataset
	path := "/projects/" + plan.ProjectID.ValueString() + "/datasets/" + found.ID
	for deadline := time.Now().Add(10 * time.Minute); ; {
		if found.IngestionStatus == nil || *found.IngestionStatus == "succeeded" || *found.IngestionStatus == "completed" {
			break
		}
		if *found.IngestionStatus == "failed" {
			reason := "it could not be read"
			if found.IngestionError != nil {
				reason = *found.IngestionError
			}
			resp.Diagnostics.AddError("Could not read the file", reason)
			return
		}
		if time.Now().After(deadline) {
			resp.Diagnostics.AddError("The file is still being read", "Pipewright is still reading it; apply again later.")
			return
		}
		time.Sleep(2 * time.Second)
		if err := r.api.Do(ctx, "GET", path, nil, &found); err != nil {
			refused(&resp.Diagnostics, "read the dataset", err)
			return
		}
	}
	plan.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *fileDatasetResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state fileDatasetModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	var found datasetAPI
	err := r.api.Do(ctx, "GET", "/projects/"+state.ProjectID.ValueString()+"/datasets/"+state.ID.ValueString(), nil, &found)
	if err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		refused(&resp.Diagnostics, "read the dataset", err)
		return
	}
	state.from(found)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

// Update is never asked for: every attribute but the counts replaces the dataset.
func (r *fileDatasetResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan fileDatasetModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *fileDatasetResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state fileDatasetModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	err := r.api.Do(ctx, "DELETE", "/projects/"+state.ProjectID.ValueString()+"/datasets/"+state.ID.ValueString(), nil, nil)
	if err != nil && !client.IsNotFound(err) {
		refused(&resp.Diagnostics, "delete the dataset", err)
	}
}
