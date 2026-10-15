package provider

import "testing"

func TestSameJSONIgnoresSpacingAndKeyOrder(t *testing.T) {
	var left, right map[string]any
	if err := decodeJSON(`{"a": 1, "b": [1, 2]}`, &left); err != nil {
		t.Fatal(err)
	}
	if err := decodeJSON(`{"b":[1,2],"a":1.0}`, &right); err != nil {
		t.Fatal(err)
	}
	if !sameJSON(left, right) {
		t.Fatal("the same settings written two ways should be the same")
	}
	if sameJSON(map[string]any{"a": 1}, map[string]any{"a": 2}) {
		t.Fatal("different settings should differ")
	}
}

func TestOnlyKeysLeavesServerDefaultsOut(t *testing.T) {
	server := map[string]any{"host": "db", "port": 5432, "sslmode": "prefer"}
	ours := map[string]any{"host": "db", "port": 5432}
	if !sameJSON(onlyKeys(server, ours), ours) {
		t.Fatal("a default the server filled in is not a change")
	}
}

func TestTasksCompareWithTheAPIsDefaultsFilledIn(t *testing.T) {
	ours := []map[string]any{{"node_key": "b", "name": "B", "node_type": "notify"},
		{"node_key": "a", "name": "A", "node_type": "transformation", "config": map[string]any{"pipeline_id": "x"}}}
	server := []map[string]any{
		{"id": "1", "node_key": "a", "name": "A", "node_type": "transformation", "config_json": map[string]any{"pipeline_id": "x"},
			"continue_on_failure": false, "retries": 0, "retry_delay_seconds": 30, "position_x": 0.0, "position_y": 0.0},
		{"id": "2", "node_key": "b", "name": "B", "node_type": "notify", "config_json": map[string]any{},
			"continue_on_failure": false, "retries": 0, "retry_delay_seconds": 30, "position_x": 1.0, "position_y": 0.0},
	}
	if !sameJSON(normalTasks(ours), normalTasks(server)) {
		t.Fatalf("got %v and %v", normalTasks(ours), normalTasks(server))
	}
	if !sameJSON(normalLinks([]map[string]any{{"from_node_key": "a", "to_node_key": "b"}}),
		normalLinks([]map[string]any{{"id": "9", "from_node_key": "a", "to_node_key": "b", "condition": "on_success"}})) {
		t.Fatal("a link without a condition follows on success")
	}
}

func TestImportIDsAreChecked(t *testing.T) {
	if _, err := splitImport("project/thing", 2, "<project id>/<id>"); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{"thing", "a/b/c", "/b", "a/"} {
		if _, err := splitImport(bad, 2, "<project id>/<id>"); err == nil {
			t.Fatalf("%q should be refused", bad)
		}
	}
}
