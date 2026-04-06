package collector

import (
	"fmt"
	"math"
	"math/rand"
	"os"
	"time"

	"github.com/arcwatch/agent/internal/types"
)

type GPUCollector struct {
	MockMode  bool
	GPUCount  int
	GPUType   string
	NodeName  string
	startTime time.Time
}

func NewGPUCollector(mockMode bool, gpuCount int, gpuType, nodeName string) *GPUCollector {
	if nodeName == "" {
		nodeName, _ = os.Hostname()
	}
	return &GPUCollector{
		MockMode:  mockMode,
		GPUCount:  gpuCount,
		GPUType:   gpuType,
		NodeName:  nodeName,
		startTime: time.Now(),
	}
}

func (c *GPUCollector) Collect() ([]types.GPUMetric, error) {
	if c.MockMode {
		return c.collectMock()
	}
	return nil, fmt.Errorf("real GPU collection not implemented — use --mock")
}

func (c *GPUCollector) collectMock() ([]types.GPUMetric, error) {
	elapsed := time.Since(c.startTime).Seconds()
	metrics := make([]types.GPUMetric, c.GPUCount)

	for i := 0; i < c.GPUCount; i++ {
		baseUtil := 40.0 + float64(i)*10.0
		wave := 15.0 * math.Sin(elapsed/30.0+float64(i))
		noise := (rand.Float64() - 0.5) * 10.0
		util := math.Max(0, math.Min(100, baseUtil+wave+noise))

		memTotal := 81920
		memUsed := int(float64(memTotal) * (0.4 + util/200.0))
		temp := 55 + int(util*0.3) + rand.Intn(5)
		power := 200 + int(util*3.5) + rand.Intn(30)

		if temp > 90 {
			temp = 90
		}
		if temp < 40 {
			temp = 40
		}
		if power > 700 {
			power = 700
		}
		if power < 100 {
			power = 100
		}

		metrics[i] = types.GPUMetric{
			GPUUUID:       fmt.Sprintf("GPU-%s-%d", c.NodeName, i),
			GPUIndex:      i,
			GPUModel:      c.GPUType,
			Utilization:   math.Round(util*10) / 10,
			MemoryUsedMB:  memUsed,
			MemoryTotalMB: memTotal,
			Temperature:   temp,
			PowerWatts:    power,
			SMClockMHz:    1410,
			MemClockMHz:   1593,
		}
	}
	return metrics, nil
}
