package exporter

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gpuwatch/agent/internal/types"
)

func TestInferenceExporterPayloadShape(t *testing.T) {
	var received types.InferencePayload
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(body, &received); err != nil {
			t.Errorf("unmarshal: %v", err)
		}
		w.WriteHeader(200)
	}))
	defer srv.Close()

	e := NewInferenceExporter(srv.URL+"/api/v1/ingest/inference/", "test-key", "llama-prod", "meta-llama/Llama-3.1-70B", srv.URL)
	raw := map[string]float64{
		"vllm:num_requests_running":                 12,
		"vllm:num_requests_waiting":                 3,
		"vllm:avg_prompt_throughput_toks_per_s":     2847.3,
		"vllm:avg_generation_throughput_toks_per_s": 342.1,
		"vllm:gpu_cache_usage_perc":                 0.87,
	}
	if err := e.Export(raw); err != nil {
		t.Fatalf("export error: %v", err)
	}
	if received.EndpointName != "llama-prod" {
		t.Errorf("endpoint_name: got %q", received.EndpointName)
	}
	if received.ModelName != "meta-llama/Llama-3.1-70B" {
		t.Errorf("model_name: got %q", received.ModelName)
	}
	if received.Engine != "vllm" {
		t.Errorf("engine: got %q", received.Engine)
	}
	if received.Metrics.RequestsRunning != 12 {
		t.Errorf("requests_running: got %v", received.Metrics.RequestsRunning)
	}
	if received.Metrics.GPUCacheUsage != 0.87 {
		t.Errorf("gpu_cache_usage: got %v", received.Metrics.GPUCacheUsage)
	}
}

func TestInferenceExporterAPIKeyHeader(t *testing.T) {
	var gotKey string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("X-API-Key")
		w.WriteHeader(200)
	}))
	defer srv.Close()

	e := NewInferenceExporter(srv.URL+"/api/v1/ingest/inference/", "secret-key", "ep", "model", srv.URL)
	e.Export(map[string]float64{})
	if gotKey != "secret-key" {
		t.Errorf("X-API-Key: got %q", gotKey)
	}
}

func TestInferenceExporterNon2xxLogsAndContinues(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
	}))
	defer srv.Close()

	e := NewInferenceExporter(srv.URL+"/api/v1/ingest/inference/", "key", "ep", "model", srv.URL)
	// Should not return an error — best-effort delivery
	err := e.Export(map[string]float64{})
	if err != nil {
		t.Errorf("expected nil error on non-2xx, got: %v", err)
	}
}

func TestInferenceExporterMissingBaseURLSkips(t *testing.T) {
	e := NewInferenceExporter("", "key", "ep", "model", "")
	err := e.Export(map[string]float64{})
	if err != nil {
		t.Errorf("expected nil when base URL empty, got: %v", err)
	}
}
