package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gpuwatch/agent/internal/collector"
	"github.com/gpuwatch/agent/internal/exporter"
	"github.com/gpuwatch/agent/internal/types"
)

func main() {
	apiURL := flag.String("api-url", "http://localhost:8000/api/v1/ingest/gpu/", "GPUWatch API URL")
	apiKey := flag.String("api-key", "", "API key for authentication")
	interval := flag.Duration("interval", 10*time.Second, "Collection interval")
	cluster := flag.String("cluster", "default", "Cluster name")
	nodeName := flag.String("node-name", "", "Node name (default: hostname)")
	mock := flag.Bool("mock", true, "Use mock GPU data")
	gpuCount := flag.Int("gpu-count", 4, "Number of mock GPUs")
	gpuType := flag.String("gpu-type", "H100-SXM", "GPU type")
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

	log.Printf("GPUWatch Agent starting (node=%s, cluster=%s, mock=%v, interval=%s)",
		name, *cluster, *mock, *interval)

	gpuCollector := collector.NewGPUCollector(*mock, *gpuCount, *gpuType, name)
	httpExporter := exporter.NewHTTPExporter(*apiURL, *apiKey)

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	ticker := time.NewTicker(*interval)
	defer ticker.Stop()

	// Collect immediately on start
	collectAndExport(gpuCollector, httpExporter, *cluster, name, *gpuType)

	for {
		select {
		case <-ticker.C:
			collectAndExport(gpuCollector, httpExporter, *cluster, name, *gpuType)
		case sig := <-sigCh:
			log.Printf("Received %s, shutting down", sig)
			return
		}
	}
}

func collectAndExport(c *collector.GPUCollector, e *exporter.HTTPExporter, cluster, nodeName, gpuType string) {
	metrics, err := c.Collect()
	if err != nil {
		log.Printf("ERROR collecting: %v", err)
		return
	}

	payload := types.NodePayload{
		Cluster:  cluster,
		NodeName: nodeName,
		GPUType:  gpuType,
		Metrics:  metrics,
	}

	if err := e.Export(payload); err != nil {
		log.Printf("ERROR exporting: %v", err)
		return
	}

	log.Printf("Exported %d GPU metrics", len(metrics))
}
