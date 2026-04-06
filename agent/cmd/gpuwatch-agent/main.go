package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/arcwatch/agent/internal/collector"
	"github.com/arcwatch/agent/internal/exporter"
	"github.com/arcwatch/agent/internal/scraper"
	"github.com/arcwatch/agent/internal/types"
)

func main() {
	// GPU collector flags
	apiURL := flag.String("api-url", "http://localhost:8000/api/v1/ingest/gpu/", "GPUWatch GPU ingest URL")
	apiKey := flag.String("api-key", "", "API key for authentication")
	interval := flag.Duration("interval", 10*time.Second, "Collection interval")
	cluster := flag.String("cluster", "default", "Cluster name")
	nodeName := flag.String("node-name", "", "Node name (default: hostname)")
	mock := flag.Bool("mock", true, "Use mock GPU data")
	gpuCount := flag.Int("gpu-count", 4, "Number of mock GPUs")
	gpuType := flag.String("gpu-type", "H100-SXM", "GPU type")

	// Inference scraper flags (optional — disabled if --vllm-url is empty)
	vllmURL := flag.String("vllm-url", "", "vLLM /metrics endpoint URL (empty = disabled)")
	endpointName := flag.String("endpoint-name", "", "Inference endpoint name (default: node hostname)")
	modelName := flag.String("model-name", "", "Model name served by this endpoint")

	flag.Parse()

	if *apiKey == "" {
		fmt.Fprintln(os.Stderr, "Error: --api-key is required")
		flag.Usage()
		os.Exit(1)
	}

	name := *nodeName
	if name == "" {
		name, _ = os.Hostname()
	}

	epName := *endpointName
	if epName == "" {
		epName = name
	}

	log.Printf("GPUWatch Agent starting (node=%s, cluster=%s, mock=%v, interval=%s)",
		name, *cluster, *mock, *interval)

	gpuCollector := collector.NewGPUCollector(*mock, *gpuCount, *gpuType, name)
	httpExporter := exporter.NewHTTPExporter(*apiURL, *apiKey)

	// Inference exporter — nil if vllm-url not provided
	var vllmScraper *scraper.VLLMScraper
	var inferenceExporter *exporter.InferenceExporter
	if *vllmURL != "" {
		inferenceBaseURL := "http://localhost:8000"
		if base := os.Getenv("GPUWATCH_BASE_URL"); base != "" {
			inferenceBaseURL = base
		}
		inferenceIngestURL := inferenceBaseURL + "/api/v1/ingest/inference/"
		vllmScraper = scraper.NewVLLMScraper(*vllmURL)
		inferenceExporter = exporter.NewInferenceExporter(
			inferenceIngestURL, *apiKey, epName, *modelName, *vllmURL,
		)
		log.Printf("Inference scraping enabled (vllm-url=%s, endpoint=%s)", *vllmURL, epName)
	}

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	ticker := time.NewTicker(*interval)
	defer ticker.Stop()

	collectAndExport(gpuCollector, httpExporter, vllmScraper, inferenceExporter, *cluster, name, *gpuType)

	for {
		select {
		case <-ticker.C:
			collectAndExport(gpuCollector, httpExporter, vllmScraper, inferenceExporter, *cluster, name, *gpuType)
		case sig := <-sigCh:
			log.Printf("Received %s, shutting down", sig)
			return
		}
	}
}

func collectAndExport(
	c *collector.GPUCollector,
	e *exporter.HTTPExporter,
	vllm *scraper.VLLMScraper,
	inf *exporter.InferenceExporter,
	cluster, nodeName, gpuType string,
) {
	// GPU metrics
	metrics, err := c.Collect()
	if err != nil {
		log.Printf("ERROR collecting GPU metrics: %v", err)
		return
	}
	payload := types.NodePayload{
		Cluster:  cluster,
		NodeName: nodeName,
		GPUType:  gpuType,
		Metrics:  metrics,
	}
	if err := e.Export(payload); err != nil {
		log.Printf("ERROR exporting GPU metrics: %v", err)
	} else {
		log.Printf("Exported %d GPU metrics", len(metrics))
	}

	// Inference metrics (optional)
	if vllm != nil && inf != nil {
		raw, err := vllm.Scrape()
		if err != nil {
			log.Printf("ERROR scraping vLLM: %v", err)
			return
		}
		if err := inf.Export(raw); err != nil {
			log.Printf("ERROR exporting inference metrics: %v", err)
		} else {
			log.Printf("Exported inference metrics (%d vLLM gauges)", len(raw))
		}
	}
}
