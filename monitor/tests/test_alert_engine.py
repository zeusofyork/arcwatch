"""monitor/tests/test_alert_engine.py"""
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase

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
