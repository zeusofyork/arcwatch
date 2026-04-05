# Design: Alert Evaluation Engine + Go Inference Exporter

**Date:** 2026-04-05
**Status:** Approved

---

## Overview

Two independent but related features that close the loop on GPUWatch's alerting and
inference pipelines:

1. **Alert Evaluation Engine** — a Celery periodic task that checks live GPU/inference
   metrics against `AlertRule` thresholds and fires `AlertEvent` rows + Slack webhooks.
2. **Go Agent Inference Exporter** — wires the Go agent's existing vLLM scraper to POST
   metrics to Django's `/api/v1/ingest/inference/` endpoint.

---

## Feature 1: Alert Evaluation Engine

### Architecture

New file: `monitor/services/alert_engine.py`

A single Celery task, `evaluate_alert_rules`, registered as a periodic beat task running
every 60 seconds. It is structurally consistent with the existing `compute_cost_snapshot`
task in `monitor/services/cost_engine.py`.

### Algorithm

```
for each enabled AlertRule in the database:
    value = fetch_metric_value(rule.organization, rule.metric)
    if value is None:
        continue
    if threshold_breached(rule, value):
        if no unresolved AlertEvent exists for this rule:
            create AlertEvent(rule, severity, message, context)
            if rule.slack_webhook_url:
                post_slack_notification(rule, value)
```

Deduplication: before creating a new `AlertEvent`, query for any existing event on the
same rule where `resolved_at IS NULL`. If one exists, skip creation. This prevents alert
storms without requiring a new `last_fired_at` field.

### Metric Mapping

| `AlertRule.metric`      | Source model          | Field / condition                          | Fires when               |
|-------------------------|-----------------------|--------------------------------------------|--------------------------|
| `gpu_utilization_low`   | `GPU`                 | `current_utilization`                      | `value < threshold`      |
| `gpu_memory_high`       | `GPU`                 | `current_memory_used_pct`                  | `value > threshold`      |
| `latency_high`          | `InferenceEndpoint`   | `current_avg_latency_ms`                   | `value > threshold`      |
| `gpu_offline`           | `GPU`                 | `status == 'offline'`                      | count > threshold (≥1)   |
| `cost_anomaly`          | cost_engine           | `get_fleet_cost_rate(org)`                 | `value > threshold`      |

For `gpu_utilization_low` and `gpu_memory_high`, the evaluation is per-GPU: an alert fires
if **any** GPU in the org breaches the threshold. The `AlertEvent.context` JSON records
which GPU(s) triggered it.

### Slack Notification

If `AlertRule.slack_webhook_url` is non-empty, the engine POSTs a simple Slack
Block Kit payload:

```json
{
  "text": "[GPUWatch] Alert: <rule.name>",
  "blocks": [
    { "type": "section", "text": { "type": "mrkdwn", "text": "*<rule.name>*\n<message>" } }
  ]
}
```

Uses `requests.post` with a 5-second timeout. Failures are logged but do not raise
(best-effort delivery). Sets `AlertEvent.notification_sent = True` on success.

### Celery Beat Registration

Added to `gpuwatch/celery.py` alongside the existing `compute_cost_snapshot` schedule:

```python
"evaluate-alert-rules": {
    "task": "monitor.evaluate_alert_rules",
    "schedule": 60.0,
},
```

### Testing

`monitor/tests/test_alert_engine.py` — unit tests using SQLite in-memory:

- Alert fires when threshold is breached
- Alert does NOT fire when threshold is not breached
- Duplicate suppression: second evaluation does not create a second event
- Slack POST is called when webhook URL is set (mock `requests.post`)
- Slack POST is skipped when webhook URL is empty
- `cost_anomaly` metric path tested via mocked `get_fleet_cost_rate`

---

## Feature 2: Go Agent Inference Exporter

### Architecture

New file: `agent/exporter/inference_exporter.go`

A struct `InferenceExporter` with a single exported method `Export(metrics VLLMMetrics)`.
Called from the main scrape loop in `agent/main.go` after each `scrapeVLLM()` call.

### Data Flow

```
scrapeVLLM() → VLLMMetrics
    → InferenceExporter.Export(metrics)
        → build JSON payload (matches Django ingest_inference schema)
        → POST /api/v1/ingest/inference/
        → log result
```

### Payload Mapping

`VLLMMetrics` fields → Django inference payload:

| Go field                   | JSON key                        |
|----------------------------|---------------------------------|
| `EndpointName`             | `endpoint_name`                 |
| `ModelName`                | `model_name`                    |
| `Engine` (hardcoded vllm)  | `engine`                        |
| `URL`                      | `url`                           |
| `RequestsRunning`          | `metrics.requests_running`      |
| `RequestsWaiting`          | `metrics.requests_waiting`      |
| `PromptThroughput`         | `metrics.prompt_throughput`     |
| `GenerationThroughput`     | `metrics.generation_throughput` |
| `GPUCacheUsage`            | `metrics.gpu_cache_usage`       |
| `CPUCacheUsage`            | `metrics.cpu_cache_usage`       |
| `LatencyP50`               | `metrics.latency_p50`           |
| `LatencyP95`               | `metrics.latency_p95`           |
| `LatencyP99`               | `metrics.latency_p99`           |
| `TTFTp50`                  | `metrics.ttft_p50`              |
| `TTFTp95`                  | `metrics.ttft_p95`              |
| `TTFTp99`                  | `metrics.ttft_p99`              |
| `TPOTAvg`                  | `metrics.tpot_avg`              |
| `PreemptionsTotal`         | `metrics.preemptions_total`     |
| `BatchSizeAvg`             | `metrics.batch_size_avg`        |

### Configuration

`InferenceExporter` reads from the same env vars as the existing GPU exporter:

| Env var              | Purpose                              |
|----------------------|--------------------------------------|
| `GPUWATCH_BASE_URL`  | Django base URL (e.g. `http://...`)  |
| `GPUWATCH_API_KEY`   | API key with `ingest` scope          |

### Error Handling

- Non-2xx responses: log the status code and body, continue (best-effort)
- Network errors: log and continue
- If `GPUWATCH_BASE_URL` is unset: skip export, log a warning once at startup

### Testing

`agent/exporter/inference_exporter_test.go` — Go unit tests:

- Correct JSON payload shape for a full `VLLMMetrics` struct
- HTTP request includes `X-API-Key` header
- Non-2xx response is logged but does not panic
- Missing `GPUWATCH_BASE_URL` skips the export without error

---

## What This Does NOT Include

- Cooldown / `last_fired_at` deduplication beyond the "open event exists" check
- Alert resolution logic (marking events as resolved when metric returns to normal)
- Slack message formatting beyond basic block kit text
- Go agent mock vLLM changes (uses existing mock)
