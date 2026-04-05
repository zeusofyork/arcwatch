# Alert Engine + Go Inference Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Celery-based alert evaluation engine that fires `AlertEvent` rows and Slack webhooks, and wire the Go agent's existing vLLM scraper to POST metrics to Django's inference ingest endpoint.

**Architecture:** Two independent features. The Python alert engine is a `@shared_task` added to `monitor/services/alert_engine.py`, registered in `CELERY_BEAT_SCHEDULE` to run every 60 s. The Go inference exporter is a new `InferenceExporter` struct in `agent/internal/exporter/inference.go`, called from `main.go` when `--vllm-url` is provided.

**Tech Stack:** Python 3, Django, Celery, `requests`; Go 1.22, `net/http`

---

## Part A — Alert Evaluation Engine (Python)

### File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `monitor/services/alert_engine.py` | Celery task + metric fetch/check helpers |
| Modify | `gpuwatch/settings.py` | Add `CELERY_BEAT_SCHEDULE` entry |
| Create | `monitor/tests/test_alert_engine.py` | Unit tests (SQLite in-memory) |

---

### Task A1: Write failing tests for alert engine

**Files:**
- Create: `monitor/tests/test_alert_engine.py`

- [ ] **Step 1: Create the test file**

```python
"""monitor/tests/test_alert_engine.py"""
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from monitor.models import GPU, GPUCluster, GPUNode, Organization, AlertRule, AlertEvent, InferenceEndpoint


def _make_org(suffix=""):
    user = User.objects.create_user(username=f"user{suffix}", password="pw")
    return Organization.objects.create(name=f"Org{suffix}", slug=f"org{suffix}", owner=user)


def _make_gpu(org, utilization=50.0, memory_used_mb=10000, memory_total_mb=80000, status="healthy"):
    cluster = GPUCluster.objects_unscoped.create(organization=org, name=f"cl-{org.slug}")
    node = GPUNode.objects_unscoped.create(
        organization=org, cluster=cluster,
        hostname=f"node-{org.slug}", gpu_count=1, gpu_type="H100",
    )
    return GPU.objects_unscoped.create(
        organization=org, node=node,
        gpu_index=0, uuid=f"GPU-{org.slug}-0",
        current_utilization=utilization,
        current_memory_used_mb=memory_used_mb,
        current_memory_total_mb=memory_total_mb,
        status=status,
    )


class AlertEngineUtilizationTest(TestCase):
    def setUp(self):
        self.org = _make_org("util")
        self.gpu = _make_gpu(self.org, utilization=10.0)
        self.rule = AlertRule.objects.create(
            organization=self.org,
            name="Low Util",
            metric="gpu_utilization_low",
            threshold_value=20.0,
        )

    def test_alert_fires_when_utilization_below_threshold(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        fired = evaluate_alert_rules()
        self.assertEqual(fired, 1)
        self.assertEqual(AlertEvent.objects.filter(rule=self.rule).count(), 1)

    def test_alert_does_not_fire_when_utilization_above_threshold(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        self.gpu.current_utilization = 80.0
        self.gpu.save()
        fired = evaluate_alert_rules()
        self.assertEqual(fired, 0)
        self.assertEqual(AlertEvent.objects.filter(rule=self.rule).count(), 0)

    def test_duplicate_suppression(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        evaluate_alert_rules()
        evaluate_alert_rules()
        self.assertEqual(AlertEvent.objects.filter(rule=self.rule).count(), 1)


class AlertEngineMemoryTest(TestCase):
    def setUp(self):
        self.org = _make_org("mem")
        # 95% memory used
        self.gpu = _make_gpu(self.org, memory_used_mb=76000, memory_total_mb=80000)
        self.rule = AlertRule.objects.create(
            organization=self.org,
            name="Mem High",
            metric="gpu_memory_high",
            threshold_value=90.0,
        )

    def test_alert_fires_when_memory_above_threshold(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        fired = evaluate_alert_rules()
        self.assertEqual(fired, 1)

    def test_alert_does_not_fire_when_memory_below_threshold(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        self.gpu.current_memory_used_mb = 40000
        self.gpu.save()
        fired = evaluate_alert_rules()
        self.assertEqual(fired, 0)


class AlertEngineLatencyTest(TestCase):
    def setUp(self):
        self.org = _make_org("lat")
        self.endpoint = InferenceEndpoint.objects_unscoped.create(
            organization=self.org,
            name="ep-lat",
            status="serving",
            current_avg_latency_ms=800.0,
        )
        self.rule = AlertRule.objects.create(
            organization=self.org,
            name="Latency High",
            metric="latency_high",
            threshold_value=500.0,
        )

    def test_alert_fires_when_latency_above_threshold(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        fired = evaluate_alert_rules()
        self.assertEqual(fired, 1)

    def test_alert_does_not_fire_when_latency_below_threshold(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        self.endpoint.current_avg_latency_ms = 200.0
        self.endpoint.save()
        fired = evaluate_alert_rules()
        self.assertEqual(fired, 0)


class AlertEngineOfflineTest(TestCase):
    def setUp(self):
        self.org = _make_org("off")
        self.gpu = _make_gpu(self.org, status="unreachable")
        self.rule = AlertRule.objects.create(
            organization=self.org,
            name="GPU Offline",
            metric="gpu_offline",
            threshold_value=1.0,
        )

    def test_alert_fires_when_gpu_unreachable(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        fired = evaluate_alert_rules()
        self.assertEqual(fired, 1)

    def test_alert_does_not_fire_when_no_offline_gpus(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        self.gpu.status = "healthy"
        self.gpu.save()
        fired = evaluate_alert_rules()
        self.assertEqual(fired, 0)


class AlertEngineCostTest(TestCase):
    def setUp(self):
        self.org = _make_org("cost")
        self.rule = AlertRule.objects.create(
            organization=self.org,
            name="Cost Spike",
            metric="cost_anomaly",
            threshold_value=50.0,
        )

    def test_alert_fires_when_cost_rate_above_threshold(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        with patch("monitor.services.alert_engine.get_fleet_cost_rate", return_value=99.0):
            fired = evaluate_alert_rules()
        self.assertEqual(fired, 1)

    def test_alert_does_not_fire_when_cost_rate_below_threshold(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        with patch("monitor.services.alert_engine.get_fleet_cost_rate", return_value=10.0):
            fired = evaluate_alert_rules()
        self.assertEqual(fired, 0)


class AlertEngineSlackTest(TestCase):
    def setUp(self):
        self.org = _make_org("slack")
        self.gpu = _make_gpu(self.org, utilization=5.0)
        self.rule = AlertRule.objects.create(
            organization=self.org,
            name="Slack Rule",
            metric="gpu_utilization_low",
            threshold_value=20.0,
            slack_webhook_url="https://hooks.slack.com/fake",
        )

    def test_slack_posted_when_webhook_set(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        with patch("monitor.services.alert_engine.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            evaluate_alert_rules()
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs[0][0], "https://hooks.slack.com/fake")

    def test_slack_not_posted_when_no_webhook(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        self.rule.slack_webhook_url = ""
        self.rule.save()
        with patch("monitor.services.alert_engine.requests.post") as mock_post:
            evaluate_alert_rules()
        mock_post.assert_not_called()

    def test_notification_sent_flag_set(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        with patch("monitor.services.alert_engine.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            evaluate_alert_rules()
        event = AlertEvent.objects.get(rule=self.rule)
        self.assertTrue(event.notification_sent)

    def test_slack_failure_does_not_raise(self):
        from monitor.services.alert_engine import evaluate_alert_rules
        with patch("monitor.services.alert_engine.requests.post", side_effect=Exception("network error")):
            # Should not raise
            evaluate_alert_rules()
        self.assertEqual(AlertEvent.objects.filter(rule=self.rule).count(), 1)
```

- [ ] **Step 2: Run tests to verify they all fail**

```bash
python manage.py test monitor.tests.test_alert_engine --verbosity=2
```

Expected: `ImportError` or `ModuleNotFoundError` — `monitor.services.alert_engine` does not exist yet.

---

### Task A2: Implement the alert engine

**Files:**
- Create: `monitor/services/alert_engine.py`

- [ ] **Step 1: Create `monitor/services/alert_engine.py`**

```python
"""
monitor/services/alert_engine.py

Alert evaluation engine.

Celery periodic task that:
  1. Loads all enabled AlertRules.
  2. Fetches the current metric value for each rule.
  3. Creates an AlertEvent if the threshold is breached and no open event exists.
  4. POSTs a Slack notification if a webhook URL is configured.
"""
import logging

import requests
from celery import shared_task

from monitor.models import AlertEvent, AlertRule, GPU, InferenceEndpoint
from monitor.services.cost_engine import get_fleet_cost_rate

logger = logging.getLogger(__name__)


@shared_task(name="monitor.evaluate_alert_rules")
def evaluate_alert_rules() -> int:
    """
    Evaluate all enabled AlertRules. Returns the number of new AlertEvents created.
    """
    rules = (
        AlertRule.objects
        .filter(is_enabled=True)
        .select_related("organization")
    )
    fired = 0
    for rule in rules:
        breached, value, ctx = _check_rule(rule)
        if not breached:
            continue
        # Deduplication: skip if an unresolved event already exists for this rule.
        if AlertEvent.objects.filter(rule=rule, resolved_at__isnull=True).exists():
            continue
        severity = _severity(rule.metric, value, rule.threshold_value)
        message = _format_message(rule, value)
        event = AlertEvent.objects.create(
            rule=rule,
            severity=severity,
            message=message,
            context=ctx,
        )
        if rule.slack_webhook_url:
            _notify_slack(rule, event)
        fired += 1
    logger.info("evaluate_alert_rules: %d new events fired", fired)
    return fired


# ── Metric check ──────────────────────────────────────────────────────────────

def _check_rule(rule: AlertRule) -> tuple:
    """
    Return (breached: bool, value: float | None, context: dict).
    """
    org = rule.organization
    metric = rule.metric
    threshold = rule.threshold_value

    if metric == "gpu_utilization_low":
        gpus = list(
            GPU.objects_unscoped.filter(
                organization=org,
                current_utilization__isnull=False,
            )
        )
        low = [g for g in gpus if g.current_utilization < threshold]
        if not low:
            return False, None, {}
        value = min(g.current_utilization for g in low)
        return True, value, {
            "gpu_count": len(low),
            "gpu_uuids": [g.uuid for g in low],
        }

    if metric == "gpu_memory_high":
        gpus = [
            g for g in GPU.objects_unscoped.filter(organization=org)
            if g.memory_utilization_pct is not None
        ]
        high = [g for g in gpus if g.memory_utilization_pct > threshold]
        if not high:
            return False, None, {}
        value = max(g.memory_utilization_pct for g in high)
        return True, value, {
            "gpu_count": len(high),
            "gpu_uuids": [g.uuid for g in high],
        }

    if metric == "latency_high":
        endpoints = list(
            InferenceEndpoint.objects_unscoped.filter(
                organization=org,
                current_avg_latency_ms__isnull=False,
            )
        )
        high = [e for e in endpoints if e.current_avg_latency_ms > threshold]
        if not high:
            return False, None, {}
        value = max(e.current_avg_latency_ms for e in high)
        return True, value, {"endpoint_count": len(high)}

    if metric == "gpu_offline":
        count = GPU.objects_unscoped.filter(
            organization=org, status="unreachable"
        ).count()
        if count < threshold:
            return False, None, {}
        return True, float(count), {"unreachable_count": count}

    if metric == "cost_anomaly":
        rate = get_fleet_cost_rate(org)
        if rate <= threshold:
            return False, None, {}
        return True, rate, {"cost_per_hour": rate}

    logger.warning("Unknown alert metric: %s", metric)
    return False, None, {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _severity(metric: str, value, threshold) -> str:
    """Derive severity from how far the value deviates from threshold."""
    if metric in ("gpu_offline", "cost_anomaly"):
        return "critical"
    if value is None:
        return "warning"
    try:
        ratio = abs(float(value) - float(threshold)) / max(abs(float(threshold)), 1.0)
    except (TypeError, ZeroDivisionError):
        return "warning"
    if ratio >= 0.5:
        return "critical"
    if ratio >= 0.2:
        return "warning"
    return "info"


def _format_message(rule: AlertRule, value) -> str:
    label = rule.get_metric_display()
    if value is not None:
        return f"{label}: current value {value:.1f} (threshold {rule.threshold_value})"
    return f"{label}: threshold {rule.threshold_value} breached"


def _notify_slack(rule: AlertRule, event: AlertEvent) -> None:
    payload = {
        "text": f"[GPUWatch] Alert: {rule.name}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{rule.name}*\n{event.message}",
                },
            }
        ],
    }
    try:
        resp = requests.post(rule.slack_webhook_url, json=payload, timeout=5)
        event.notification_sent = resp.status_code == 200
        event.save(update_fields=["notification_sent"])
    except Exception as exc:
        logger.warning("Slack notification failed for rule %s: %s", rule.name, exc)
```

- [ ] **Step 2: Run the tests — they should pass now**

```bash
python manage.py test monitor.tests.test_alert_engine --verbosity=2
```

Expected: all tests pass, `OK`.

- [ ] **Step 3: Commit**

```bash
git add monitor/services/alert_engine.py monitor/tests/test_alert_engine.py
git commit -m "feat: alert evaluation engine with Slack notifications"
```

---

### Task A3: Register the Celery beat task

**Files:**
- Modify: `gpuwatch/settings.py`

- [ ] **Step 1: Add `CELERY_BEAT_SCHEDULE` to settings.py**

Open `gpuwatch/settings.py`. Find the Celery config block (around line 127 where `CELERY_BROKER_URL` is defined). Add this block immediately after the existing Celery settings:

```python
CELERY_BEAT_SCHEDULE = {
    "compute-cost-snapshot": {
        "task": "monitor.compute_cost_snapshot",
        "schedule": 60.0,
    },
    "evaluate-alert-rules": {
        "task": "monitor.evaluate_alert_rules",
        "schedule": 60.0,
    },
}
```

- [ ] **Step 2: Verify Django check passes**

```bash
python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Commit**

```bash
git add gpuwatch/settings.py
git commit -m "feat: register evaluate_alert_rules as Celery beat task (60s)"
```

---

## Part B — Go Inference Exporter

### File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `agent/internal/types/metrics.go` | Add `InferencePayload` + `InferenceMetrics` structs |
| Create | `agent/internal/exporter/inference.go` | `InferenceExporter` — maps vLLM metrics → Django payload, POSTs |
| Create | `agent/internal/exporter/inference_test.go` | Unit tests |
| Modify | `agent/cmd/gpuwatch-agent/main.go` | Add `--vllm-*` flags, wire exporter into loop |

---

### Task B1: Add inference types

**Files:**
- Modify: `agent/internal/types/metrics.go`

- [ ] **Step 1: Append inference types to `agent/internal/types/metrics.go`**

Add these structs at the end of the file (after the existing `NodePayload` struct):

```go
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
	EndpointName string          `json:"endpoint_name"`
	ModelName    string          `json:"model_name"`
	Engine       string          `json:"engine"`
	URL          string          `json:"url"`
	Metrics      InferenceMetrics `json:"metrics"`
}
```

- [ ] **Step 2: Verify the package still compiles**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch/agent && go build ./...
```

Expected: no output (success).

---

### Task B2: Write failing tests for InferenceExporter

**Files:**
- Create: `agent/internal/exporter/inference_test.go`

- [ ] **Step 1: Create the test file**

```go
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
		"vllm:num_requests_running":                12,
		"vllm:num_requests_waiting":                3,
		"vllm:avg_prompt_throughput_toks_per_s":    2847.3,
		"vllm:avg_generation_throughput_toks_per_s": 342.1,
		"vllm:gpu_cache_usage_perc":                0.87,
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch/agent && go test ./internal/exporter/... -v
```

Expected: compile error — `NewInferenceExporter` undefined.

---

### Task B3: Implement InferenceExporter

**Files:**
- Create: `agent/internal/exporter/inference.go`

- [ ] **Step 1: Create `agent/internal/exporter/inference.go`**

```go
package exporter

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"github.com/gpuwatch/agent/internal/types"
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
```

- [ ] **Step 2: Run the tests — they should pass now**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch/agent && go test ./internal/exporter/... -v
```

Expected: all four `TestInferenceExporter*` tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch/agent
git add internal/types/metrics.go internal/exporter/inference.go internal/exporter/inference_test.go
git commit -m "feat: Go InferenceExporter — maps vLLM metrics to Django ingest payload"
```

---

### Task B4: Wire InferenceExporter into main.go

**Files:**
- Modify: `agent/cmd/gpuwatch-agent/main.go`

- [ ] **Step 1: Replace `main.go` with the wired version**

```go
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
	"github.com/gpuwatch/agent/internal/scraper"
	"github.com/gpuwatch/agent/internal/types"
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
```

- [ ] **Step 2: Build to verify no compile errors**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch/agent && go build ./...
```

Expected: no output.

- [ ] **Step 3: Run all Go tests**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch/agent && go test ./... -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch/agent
git add cmd/gpuwatch-agent/main.go
git commit -m "feat: wire vLLM scraper to inference exporter in agent main loop"
```

---

## Final Step: Commit the uncommitted work from the previous session

The inference/cost/alerting work from the prior session is still uncommitted. Commit it before merging:

- [ ] **Step 1: Commit prior session's work**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch
git add \
  monitor/migrations/0003_inference_hypertable.py \
  monitor/migrations/0004_gpu_pricing.py \
  monitor/migrations/0005_cost_hypertable.py \
  monitor/migrations/0006_alertevent_alertrule_and_more.py \
  monitor/models/alert.py \
  monitor/models/cost.py \
  monitor/models/__init__.py \
  monitor/models/inference.py \
  monitor/services/cost_engine.py \
  monitor/services/inference_ingestion.py \
  monitor/templates/monitor/alerts_dashboard.html \
  monitor/templates/monitor/cost_attribution.html \
  monitor/templates/monitor/inference_dashboard.html \
  monitor/tests/test_inference_and_cost.py \
  monitor/views/alert_views.py \
  monitor/views/cost_views.py \
  monitor/views/inference_views.py \
  monitor/admin.py \
  monitor/management/commands/seed_demo_data.py \
  monitor/rest_api.py \
  monitor/templates/monitor/base.html \
  monitor/urls.py
git commit -m "feat: inference tracking, cost attribution, and alerting dashboards"
```
