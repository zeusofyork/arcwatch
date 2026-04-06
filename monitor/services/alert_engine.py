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
        "text": f"[ArcWatch] Alert: {rule.name}",
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
