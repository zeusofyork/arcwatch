package types

type GPUMetric struct {
	GPUUUID       string  `json:"gpu_uuid"`
	GPUIndex      int     `json:"gpu_index"`
	GPUModel      string  `json:"gpu_model"`
	Utilization   float64 `json:"utilization"`
	MemoryUsedMB  int     `json:"memory_used_mb"`
	MemoryTotalMB int     `json:"memory_total_mb"`
	Temperature   int     `json:"temperature"`
	PowerWatts    int     `json:"power_watts"`
	SMClockMHz    int     `json:"sm_clock_mhz"`
	MemClockMHz   int     `json:"mem_clock_mhz"`
	PCIeTxBytes   int64   `json:"pcie_tx_bytes"`
	PCIeRxBytes   int64   `json:"pcie_rx_bytes"`
	ECCSingle     int     `json:"ecc_single"`
	ECCDouble     int     `json:"ecc_double"`
}

type NodePayload struct {
	Cluster  string      `json:"cluster"`
	NodeName string      `json:"node_name"`
	GPUType  string      `json:"gpu_type"`
	Metrics  []GPUMetric `json:"metrics"`
}

// InferenceMetrics holds vLLM Prometheus metric values mapped to
// the Django inference ingest schema.
type InferenceMetrics struct {
	RequestsRunning      float64 `json:"requests_running"`
	RequestsWaiting      float64 `json:"requests_waiting"`
	PromptThroughput     float64 `json:"prompt_throughput"`
	GenerationThroughput float64 `json:"generation_throughput"`
	GPUCacheUsage        float64 `json:"gpu_cache_usage"`
	CPUCacheUsage        float64 `json:"cpu_cache_usage"`
}

// InferencePayload is the JSON body sent to POST /api/v1/ingest/inference/.
type InferencePayload struct {
	EndpointName string           `json:"endpoint_name"`
	ModelName    string           `json:"model_name"`
	Engine       string           `json:"engine"`
	URL          string           `json:"url"`
	Metrics      InferenceMetrics `json:"metrics"`
}
