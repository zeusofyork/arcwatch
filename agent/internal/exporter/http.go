package exporter

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/gpuwatch/agent/internal/types"
)

type HTTPExporter struct {
	URL    string
	APIKey string
	client *http.Client
}

func NewHTTPExporter(url, apiKey string) *HTTPExporter {
	return &HTTPExporter{
		URL:    url,
		APIKey: apiKey,
		client: &http.Client{Timeout: 10 * time.Second},
	}
}

func (e *HTTPExporter) Export(payload types.NodePayload) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}

	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 {
			time.Sleep(time.Duration(1<<attempt) * time.Second)
		}

		req, err := http.NewRequest("POST", e.URL, bytes.NewReader(body))
		if err != nil {
			return fmt.Errorf("create request: %w", err)
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-API-Key", e.APIKey)

		resp, err := e.client.Do(req)
		if err != nil {
			lastErr = fmt.Errorf("attempt %d: %w", attempt+1, err)
			continue
		}
		respBody, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		if resp.StatusCode == 200 {
			return nil
		}
		lastErr = fmt.Errorf("attempt %d: status %d: %s", attempt+1, resp.StatusCode, string(respBody))
	}
	return fmt.Errorf("export failed after 3 attempts: %w", lastErr)
}
