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
