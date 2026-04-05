"""
monitor/tests/test_inference_and_cost.py

Tests for inference metric ingestion, cost model, and alert models.
Uses SQLite in-memory (same pattern as the existing test suite).
"""
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from monitor.models import (
    GPU,
    GPUCluster,
    GPUNode,
    GPUPricing,
    InferenceEndpoint,
    Organization,
    AlertRule,
    AlertEvent,
)
from monitor.services.inference_ingestion import ingest_inference_metrics


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_org(suffix=""):
    user = User.objects.create_user(username=f"user{suffix}", password="pw")
    org = Organization.objects.create(
        name=f"Org{suffix}", slug=f"org{suffix}", owner=user
    )
    return org


def _sample_inference_payload(name="llama-prod", model="meta-llama/Llama-3.1-70B"):
    return {
        "endpoint_name": name,
        "model_name": model,
        "engine": "vllm",
        "url": "http://localhost:8000/v1",
        "metrics": {
            "requests_running": 10,
            "requests_waiting": 2,
            "prompt_throughput": 400.0,
            "generation_throughput": 1800.0,
            "gpu_cache_usage": 0.72,
            "cpu_cache_usage": 0.05,
            "latency_p50": 90.0,
            "latency_p95": 280.0,
            "latency_p99": 550.0,
            "ttft_p50": 30.0,
            "ttft_p95": 95.0,
            "ttft_p99": 210.0,
            "tpot_avg": 4.2,
            "preemptions_total": 0,
            "batch_size_avg": 8.5,
        },
    }


# ── InferenceEndpoint creation via ingest ─────────────────────────────────────

class InferenceIngestionTest(TestCase):

    def setUp(self):
        self.org = _make_org("inf")

    def test_ingest_creates_endpoint(self):
        """ingest_inference_metrics creates an InferenceEndpoint on first call."""
        count = ingest_inference_metrics(self.org, _sample_inference_payload())
        self.assertEqual(count, 1)
        ep = InferenceEndpoint.objects_unscoped.get(
            organization=self.org, name="llama-prod"
        )
        self.assertEqual(ep.engine, "vllm")
        self.assertEqual(ep.current_model, "meta-llama/Llama-3.1-70B")
        self.assertEqual(ep.status, "serving")

    def test_ingest_updates_existing_endpoint(self):
        """Second ingest call updates the endpoint snapshot."""
        ingest_inference_metrics(self.org, _sample_inference_payload())
        # Second call with different metrics
        payload2 = _sample_inference_payload()
        payload2["metrics"]["generation_throughput"] = 2500.0
        payload2["metrics"]["latency_p50"] = 60.0
        ingest_inference_metrics(self.org, payload2)

        ep = InferenceEndpoint.objects_unscoped.get(
            organization=self.org, name="llama-prod"
        )
        self.assertAlmostEqual(ep.current_tokens_per_sec, 2500.0, places=0)
        self.assertAlmostEqual(ep.current_avg_latency_ms, 60.0, places=0)

    def test_ingest_writes_hypertable_row(self):
        """ingest_inference_metrics writes a row to the inference_metrics table."""
        ingest_inference_metrics(self.org, _sample_inference_payload())
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM inference_metrics WHERE model_name = %s",
                ["meta-llama/Llama-3.1-70B"],
            )
            count = cur.fetchone()[0]
        self.assertEqual(count, 1)

    def test_ingest_missing_endpoint_name_raises(self):
        """ingest raises ValueError when endpoint_name is absent."""
        with self.assertRaises(ValueError):
            ingest_inference_metrics(self.org, {"metrics": {}})

    def test_ingest_updates_kv_cache_pct(self):
        """gpu_cache_usage fraction (0-1) is converted to percent (0-100)."""
        ingest_inference_metrics(self.org, _sample_inference_payload())
        ep = InferenceEndpoint.objects_unscoped.get(
            organization=self.org, name="llama-prod"
        )
        # 0.72 should become 72.0
        self.assertAlmostEqual(ep.current_kv_cache_usage_pct, 72.0, places=1)


# ── InferenceEndpoint model ───────────────────────────────────────────────────

class InferenceEndpointModelTest(TestCase):

    def setUp(self):
        self.org = _make_org("ep")

    def test_create_endpoint_and_str(self):
        ep = InferenceEndpoint.objects_unscoped.create(
            organization=self.org,
            name="mistral-7b",
            engine="tgi",
        )
        self.assertIn("mistral-7b", str(ep))
        self.assertIn("tgi", str(ep))

    def test_endpoint_default_status_idle(self):
        ep = InferenceEndpoint.objects_unscoped.create(
            organization=self.org,
            name="test-ep",
        )
        self.assertEqual(ep.status, "idle")

    def test_endpoint_unique_name_per_org(self):
        from django.db import IntegrityError
        InferenceEndpoint.objects_unscoped.create(
            organization=self.org, name="dup-ep"
        )
        with self.assertRaises(IntegrityError):
            InferenceEndpoint.objects_unscoped.create(
                organization=self.org, name="dup-ep"
            )


# ── GPUPricing model ──────────────────────────────────────────────────────────

class GPUPricingModelTest(TestCase):

    def test_create_pricing_and_str(self):
        p = GPUPricing.objects.create(
            gpu_model_pattern="H100",
            hourly_rate="12.2900",
            provider="CoreWeave",
            pricing_type="on_demand",
        )
        self.assertIn("H100", str(p))
        self.assertIn("12.2900", str(p))

    def test_pricing_default_type(self):
        p = GPUPricing.objects.create(
            gpu_model_pattern="A100",
            hourly_rate="8.50",
        )
        self.assertEqual(p.pricing_type, "on_demand")


# ── AlertRule + AlertEvent models ─────────────────────────────────────────────

class AlertModelTest(TestCase):

    def setUp(self):
        self.org = _make_org("alert")

    def test_create_alert_rule_and_str(self):
        rule = AlertRule.objects.create(
            organization=self.org,
            name="Low Util Rule",
            metric="gpu_utilization_low",
            threshold_value=20.0,
        )
        self.assertIn("Low Util Rule", str(rule))
        self.assertIn("GPU Underutilization", str(rule))

    def test_alert_rule_default_enabled(self):
        rule = AlertRule.objects.create(
            organization=self.org,
            name="Default Rule",
            metric="gpu_offline",
            threshold_value=1.0,
        )
        self.assertTrue(rule.is_enabled)

    def test_alert_rule_duration_default(self):
        rule = AlertRule.objects.create(
            organization=self.org,
            name="Dur Rule",
            metric="cost_anomaly",
            threshold_value=100.0,
        )
        self.assertEqual(rule.duration_seconds, 300)

    def test_create_alert_event_and_str(self):
        rule = AlertRule.objects.create(
            organization=self.org,
            name="Latency Rule",
            metric="latency_high",
            threshold_value=500.0,
        )
        event = AlertEvent.objects.create(
            rule=rule,
            severity="critical",
            message="Latency spike detected",
            context={"value": 750.0},
        )
        self.assertIn("Latency Rule", str(event))
        self.assertTrue(event.is_active)

    def test_alert_event_resolved_not_active(self):
        rule = AlertRule.objects.create(
            organization=self.org,
            name="Rule2",
            metric="gpu_memory_high",
            threshold_value=90.0,
        )
        event = AlertEvent.objects.create(
            rule=rule,
            severity="warning",
            message="Memory high",
            resolved_at=timezone.now(),
        )
        self.assertFalse(event.is_active)
