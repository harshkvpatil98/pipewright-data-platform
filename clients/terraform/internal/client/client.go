// Package client talks to Pipewright's API for the Terraform provider.
//
// Every call is JSON over HTTPS with an API token. An API error carries the
// status and Pipewright's own sentence ("detail"), which the provider passes on
// as the diagnostic, so a refusal reads the same in Terraform as in the app.
package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// fileTypes says what a file is by its extension, the way Pipewright checks an upload.
var fileTypes = map[string]string{
	".csv":     "text/csv",
	".tsv":     "text/tab-separated-values",
	".txt":     "text/plain",
	".json":    "application/json",
	".jsonl":   "application/json",
	".xlsx":    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	".xls":     "application/vnd.ms-excel",
	".parquet": "application/octet-stream",
}

func fileType(name string) string {
	extension := strings.ToLower(filepath.Ext(name))
	if known, ok := fileTypes[extension]; ok {
		return known
	}
	if guessed := mime.TypeByExtension(extension); guessed != "" {
		return guessed
	}
	return "application/octet-stream"
}

// Client is a signed-in connection to one Pipewright deployment.
type Client struct {
	base  string
	token string
	http  *http.Client
}

// APIError is a refusal from the API, with Pipewright's own explanation.
type APIError struct {
	Status int
	Detail string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("Pipewright answered %d: %s", e.Status, e.Detail)
}

// IsNotFound says whether an error means the thing is not there (any more).
func IsNotFound(err error) bool {
	var apiErr *APIError
	return errors.As(err, &apiErr) && apiErr.Status == http.StatusNotFound
}

// New makes a client for the deployment at baseURL (its address, such as
// https://pipewright.example.com) with an API token.
func New(baseURL, token string) (*Client, error) {
	trimmed := strings.TrimRight(strings.TrimSpace(baseURL), "/")
	if trimmed == "" {
		return nil, errors.New("give the address of Pipewright, such as https://pipewright.example.com")
	}
	if _, err := url.ParseRequestURI(trimmed); err != nil {
		return nil, fmt.Errorf("%q is not an address: %w", baseURL, err)
	}
	if !strings.HasPrefix(token, "pw_") {
		return nil, errors.New("the token is an API token from Your settings → API tokens; it starts with pw_")
	}
	trimmed = strings.TrimSuffix(trimmed, "/api/v1")
	return &Client{base: trimmed + "/api/v1", token: token, http: &http.Client{Timeout: 120 * time.Second}}, nil
}

// Do sends a request and decodes the answer into out, if any.
func (c *Client) Do(ctx context.Context, method, path string, body, out any) error {
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(encoded)
	}
	request, err := http.NewRequestWithContext(ctx, method, c.base+path, reader)
	if err != nil {
		return err
	}
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	return c.send(request, out)
}

// Upload sends a file as a new dataset, named name.
func (c *Client) Upload(ctx context.Context, projectID, name, source string, out any) error {
	file, err := os.Open(source)
	if err != nil {
		return err
	}
	defer file.Close()
	var buffer bytes.Buffer
	form := multipart.NewWriter(&buffer)
	header := make(textproto.MIMEHeader)
	header.Set("Content-Disposition", fmt.Sprintf(`form-data; name="file"; filename=%q`, filepath.Base(source)))
	header.Set("Content-Type", fileType(source))
	part, err := form.CreatePart(header)
	if err != nil {
		return err
	}
	if _, err := io.Copy(part, file); err != nil {
		return err
	}
	if err := form.Close(); err != nil {
		return err
	}
	path := fmt.Sprintf("%s/projects/%s/datasets/upload?dataset_name=%s", c.base, projectID, url.QueryEscape(name))
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, path, &buffer)
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", form.FormDataContentType())
	return c.send(request, out)
}

func (c *Client) send(request *http.Request, out any) error {
	request.Header.Set("Authorization", "Bearer "+c.token)
	request.Header.Set("Accept", "application/json")
	request.Header.Set("User-Agent", "terraform-provider-pipewright")
	response, err := c.http.Do(request)
	if err != nil {
		return fmt.Errorf("could not reach Pipewright: %w", err)
	}
	defer response.Body.Close()
	payload, err := io.ReadAll(response.Body)
	if err != nil {
		return err
	}
	if response.StatusCode >= 300 {
		return &APIError{Status: response.StatusCode, Detail: detail(payload)}
	}
	if out == nil || len(payload) == 0 {
		return nil
	}
	return json.Unmarshal(payload, out)
}

// detail is Pipewright's sentence for a refusal, or the body as it came.
func detail(payload []byte) string {
	var answer struct {
		Detail any `json:"detail"`
	}
	if json.Unmarshal(payload, &answer) == nil && answer.Detail != nil {
		if text, ok := answer.Detail.(string); ok {
			return text
		}
		encoded, _ := json.Marshal(answer.Detail)
		return string(encoded)
	}
	return strings.TrimSpace(string(payload))
}
