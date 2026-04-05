package exporter

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gpuwatch/agent/internal/types"
)

func TestExportSuccess(t *testing.T) {
	var received types.NodePayload
	var gotKey string

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("X-API-Key")
		json.NewDecoder(r.Body).Decode(&received)
		w.Write([]byte(`{"status":"ok","metrics_ingested":1}`))
	}))
	defer srv.Close()

	exp := NewHTTPExporter(srv.URL, "test-key-123")
	payload := types.NodePayload{
		Cluster:  "test",
		NodeName: "node-1",
		GPUType:  "H100",
		Metrics:  []types.GPUMetric{{GPUUUID: "GPU-001", Utilization: 85.0}},
	}

	err := exp.Export(payload)
	if err != nil {
		t.Fatalf("export error: %v", err)
	}
	if gotKey != "test-key-123" {
		t.Errorf("expected API key test-key-123, got %s", gotKey)
	}
	if received.NodeName != "node-1" {
		t.Errorf("expected node-1, got %s", received.NodeName)
	}
	if len(received.Metrics) != 1 {
		t.Errorf("expected 1 metric, got %d", len(received.Metrics))
	}
}

func TestExportRetry(t *testing.T) {
	attempts := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts++
		if attempts < 3 {
			w.WriteHeader(500)
			w.Write([]byte(`{"error":"internal"}`))
			return
		}
		w.Write([]byte(`{"status":"ok","metrics_ingested":1}`))
	}))
	defer srv.Close()

	exp := NewHTTPExporter(srv.URL, "key")
	err := exp.Export(types.NodePayload{NodeName: "n", Metrics: []types.GPUMetric{{}}})
	if err != nil {
		t.Fatalf("expected success after retries, got: %v", err)
	}
	if attempts != 3 {
		t.Errorf("expected 3 attempts, got %d", attempts)
	}
}

func TestExportAuthHeader(t *testing.T) {
	var headers http.Header
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		headers = r.Header
		w.Write([]byte(`{"status":"ok"}`))
	}))
	defer srv.Close()

	exp := NewHTTPExporter(srv.URL, "gpuwatch_abc123")
	exp.Export(types.NodePayload{Metrics: []types.GPUMetric{{}}})

	if headers.Get("X-API-Key") != "gpuwatch_abc123" {
		t.Errorf("wrong API key header: %s", headers.Get("X-API-Key"))
	}
	if headers.Get("Content-Type") != "application/json" {
		t.Errorf("wrong content type: %s", headers.Get("Content-Type"))
	}
}
