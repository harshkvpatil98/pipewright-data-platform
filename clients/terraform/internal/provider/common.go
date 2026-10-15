package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"strings"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/client"
)

// configured hands a resource or data source the provider's client.
func configured(data any, diags *diag.Diagnostics) *client.Client {
	if data == nil {
		return nil // Terraform asks before the provider is configured; that is expected.
	}
	api, ok := data.(*client.Client)
	if !ok {
		diags.AddError("Unexpected provider data", fmt.Sprintf("expected *client.Client, got %T", data))
		return nil
	}
	return api
}

// refused adds an API error as a diagnostic, Pipewright's sentence first.
func refused(diags *diag.Diagnostics, what string, err error) {
	diags.AddError(fmt.Sprintf("Could not %s", what), err.Error())
}

// splitImport reads an import id such as "<project id>/<id>".
func splitImport(id string, parts int, shape string) ([]string, error) {
	found := strings.Split(id, "/")
	if len(found) != parts {
		return nil, fmt.Errorf("import with %s, not %q", shape, id)
	}
	for _, part := range found {
		if strings.TrimSpace(part) == "" {
			return nil, fmt.Errorf("import with %s, not %q", shape, id)
		}
	}
	return found, nil
}

// importTwo sets project_id and id from "<project id>/<id>".
func importTwo(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	parts, err := splitImport(req.ID, 2, "<project id>/<id>")
	if err != nil {
		resp.Diagnostics.AddError("Cannot import", err.Error())
		return
	}
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, pathOf("project_id"), parts[0])...)
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, pathOf("id"), parts[1])...)
}

func pathOf(name string) path.Path { return path.Root(name) }

// optionalString is nil for an unset attribute, so the API leaves the field alone.
func optionalString(value types.String) *string {
	if value.IsNull() || value.IsUnknown() {
		return nil
	}
	text := value.ValueString()
	return &text
}

func stringOrNull(value *string) types.String {
	if value == nil {
		return types.StringNull()
	}
	return types.StringValue(*value)
}

// decodeJSON reads an attribute written with jsonencode().
func decodeJSON(text string, into any) error {
	if strings.TrimSpace(text) == "" {
		text = "null"
	}
	if err := json.Unmarshal([]byte(text), into); err != nil {
		return fmt.Errorf("this is not JSON (write it with jsonencode): %w", err)
	}
	return nil
}

// sameJSON says whether two values mean the same once read as JSON, whatever
// their spacing or key order.
func sameJSON(left, right any) bool {
	return reflect.DeepEqual(normalJSON(left), normalJSON(right))
}

func normalJSON(value any) any {
	encoded, err := json.Marshal(value)
	if err != nil {
		return value
	}
	var out any
	_ = json.Unmarshal(encoded, &out)
	return out
}

// encodeJSON writes a value as compact JSON, keys in order.
func encodeJSON(value any) string {
	encoded, err := json.Marshal(normalJSON(value))
	if err != nil {
		return "null"
	}
	return string(encoded)
}

// onlyKeys keeps the keys of `server` that `ours` has: the settings this
// configuration manages, leaving defaults the server filled in out of the diff.
func onlyKeys(server, ours map[string]any) map[string]any {
	kept := map[string]any{}
	for key := range ours {
		if value, ok := server[key]; ok {
			kept[key] = value
		}
	}
	return kept
}
