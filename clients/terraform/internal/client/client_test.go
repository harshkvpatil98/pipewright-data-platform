package client

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestNewRefusesWhatIsNotAnAddressOrAToken(t *testing.T) {
	if _, err := New("", "pw_x"); err == nil {
		t.Fatal("an empty address should be refused")
	}
	if _, err := New("https://pipewright.example.com", "eyJhbGci"); err == nil || !strings.Contains(err.Error(), "pw_") {
		t.Fatalf("a sign-in token is not an API token: %v", err)
	}
	api, err := New("https://pipewright.example.com/api/v1/", "pw_x")
	if err != nil || api.base != "https://pipewright.example.com/api/v1" {
		t.Fatalf("the address may carry /api/v1 already: %v %q", err, api.base)
	}
}

func TestARefusalCarriesPipewrightsSentence(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer pw_secret" {
			t.Errorf("the token is sent: %q", r.Header.Get("Authorization"))
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = io.WriteString(w, `{"detail":"Project not found."}`)
	}))
	defer server.Close()
	api, _ := New(server.URL, "pw_secret")
	err := api.Do(context.Background(), "GET", "/projects/x", nil, nil)
	if !IsNotFound(err) || !strings.Contains(err.Error(), "Project not found.") {
		t.Fatalf("got %v", err)
	}
}

func TestAnUploadSaysWhatKindOfFileItIs(t *testing.T) {
	var gotType, gotName, gotQuery string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		file, header, err := r.FormFile("file")
		if err != nil {
			t.Fatal(err)
		}
		defer file.Close()
		gotType, gotName, gotQuery = header.Header.Get("Content-Type"), header.Filename, r.URL.RawQuery
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, `{"dataset":{"id":"d1","name":"Orders"}}`)
	}))
	defer server.Close()
	source := filepath.Join(t.TempDir(), "orders.csv")
	if err := os.WriteFile(source, []byte("id,amount\n1,2\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	api, _ := New(server.URL, "pw_secret")
	var out struct {
		Dataset struct{ ID string } `json:"dataset"`
	}
	if err := api.Upload(context.Background(), "p1", "Orders and more", source, &out); err != nil {
		t.Fatal(err)
	}
	if gotType != "text/csv" || gotName != "orders.csv" || gotQuery != "dataset_name=Orders+and+more" || out.Dataset.ID != "d1" {
		t.Fatalf("type %q, name %q, query %q, id %q", gotType, gotName, gotQuery, out.Dataset.ID)
	}
}
