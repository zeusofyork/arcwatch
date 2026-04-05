package collector

import "testing"

func TestMockCollector(t *testing.T) {
	c := NewGPUCollector(true, 4, "H100-SXM", "test-node")
	metrics, err := c.Collect()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(metrics) != 4 {
		t.Fatalf("expected 4 metrics, got %d", len(metrics))
	}
	for i, m := range metrics {
		if m.GPUIndex != i {
			t.Errorf("gpu %d: expected index %d, got %d", i, i, m.GPUIndex)
		}
		if m.Utilization < 0 || m.Utilization > 100 {
			t.Errorf("gpu %d: utilization %.1f out of range", i, m.Utilization)
		}
		if m.Temperature < 40 || m.Temperature > 90 {
			t.Errorf("gpu %d: temperature %d out of range", i, m.Temperature)
		}
		if m.GPUUUID == "" {
			t.Errorf("gpu %d: empty UUID", i)
		}
		if m.GPUModel != "H100-SXM" {
			t.Errorf("gpu %d: expected model H100-SXM, got %s", i, m.GPUModel)
		}
	}
}

func TestRealCollectorFails(t *testing.T) {
	c := NewGPUCollector(false, 1, "H100", "test")
	_, err := c.Collect()
	if err == nil {
		t.Error("expected error for non-mock mode without GPUs")
	}
}
