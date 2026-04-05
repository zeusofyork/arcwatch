package scraper

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const sampleVLLMMetrics = `# HELP vllm:num_requests_running Number of running requests
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running 12
# HELP vllm:num_requests_waiting Number of waiting requests
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting 3
# HELP vllm:avg_prompt_throughput_toks_per_s Avg prompt throughput
# TYPE vllm:avg_prompt_throughput_toks_per_s gauge
vllm:avg_prompt_throughput_toks_per_s 2847.3
# HELP vllm:avg_generation_throughput_toks_per_s Avg generation throughput
# TYPE vllm:avg_generation_throughput_toks_per_s gauge
vllm:avg_generation_throughput_toks_per_s 342.1
# HELP vllm:gpu_cache_usage_perc GPU cache usage
# TYPE vllm:gpu_cache_usage_perc gauge
vllm:gpu_cache_usage_perc 0.87
`

func TestParsePrometheusText(t *testing.T) {
	result, err := ParsePrometheusText(strings.NewReader(sampleVLLMMetrics))
	if err != nil {
		t.Fatalf("parse error: %v", err)
	}
	checks := map[string]float64{
		"vllm:num_requests_running":                12,
		"vllm:num_requests_waiting":                3,
		"vllm:avg_prompt_throughput_toks_per_s":     2847.3,
		"vllm:avg_generation_throughput_toks_per_s": 342.1,
		"vllm:gpu_cache_usage_perc":                0.87,
	}
	for name, expected := range checks {
		got, ok := result[name]
		if !ok {
			t.Errorf("missing metric %s", name)
			continue
		}
		if got != expected {
			t.Errorf("%s: expected %v, got %v", name, expected, got)
		}
	}
}

func TestScrapeHTTP(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(sampleVLLMMetrics))
	}))
	defer srv.Close()

	s := NewVLLMScraper(srv.URL)
	result, err := s.Scrape()
	if err != nil {
		t.Fatalf("scrape error: %v", err)
	}
	if result["vllm:num_requests_running"] != 12 {
		t.Errorf("expected 12, got %v", result["vllm:num_requests_running"])
	}
}

func TestScrapeError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
	}))
	defer srv.Close()

	s := NewVLLMScraper(srv.URL)
	_, err := s.Scrape()
	if err == nil {
		t.Error("expected error on 500 response")
	}
}
