package exporter

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"github.com/arcwatch/agent/internal/types"
)

// InferenceExporter sends vLLM metrics to the Django inference ingest endpoint.
// Delivery is best-effort: non-2xx responses and network errors are logged but
// do not return an error to the caller.
type InferenceExporter struct {
	url          string // full URL: base + /api/v1/ingest/inference/
	apiKey       string
	endpointName string
	modelName    string
	scrapeURL    string // original vLLM metrics URL (forwarded as payload.url)
	client       *http.Client
}

// NewInferenceExporter constructs an InferenceExporter.
// If url is empty the exporter is disabled and Export() is a no-op.
func NewInferenceExporter(url, apiKey, endpointName, modelName, scrapeURL string) *InferenceExporter {
	return &InferenceExporter{
		url:          url,
		apiKey:       apiKey,
		endpointName: endpointName,
		modelName:    modelName,
		scrapeURL:    scrapeURL,
		client:       &http.Client{Timeout: 10 * time.Second},
	}
}

// Export maps a raw vLLM Prometheus metric map to the Django inference payload
// and POSTs it. Returns nil on success or on best-effort failure (non-2xx).
// Returns a non-nil error only for programming errors (e.g. JSON marshal failure).
func (e *InferenceExporter) Export(raw map[string]float64) error {
	if e.url == "" {
		return nil
	}

	payload := types.InferencePayload{
		EndpointName: e.endpointName,
		ModelName:    e.modelName,
		Engine:       "vllm",
		URL:          e.scrapeURL,
		Metrics: types.InferenceMetrics{
			RequestsRunning:      raw["vllm:num_requests_running"],
			RequestsWaiting:      raw["vllm:num_requests_waiting"],
			PromptThroughput:     raw["vllm:avg_prompt_throughput_toks_per_s"],
			GenerationThroughput: raw["vllm:avg_generation_throughput_toks_per_s"],
			GPUCacheUsage:        raw["vllm:gpu_cache_usage_perc"],
			CPUCacheUsage:        raw["vllm:cpu_cache_usage_perc"],
		},
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("inference exporter: marshal: %w", err)
	}

	req, err := http.NewRequest("POST", e.url, bytes.NewReader(body))
	if err != nil {
		log.Printf("inference exporter: create request: %v", err)
		return nil
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", e.apiKey)

	resp, err := e.client.Do(req)
	if err != nil {
		log.Printf("inference exporter: POST failed: %v", err)
		return nil
	}
	respBody, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	if resp.StatusCode != 200 {
		log.Printf("inference exporter: status %d: %s", resp.StatusCode, string(respBody))
	}
	return nil
}
