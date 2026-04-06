"""
monitor/services/llm_sync_engine.py

LLM API usage sync engine.

Components:
  encrypt_api_key / decrypt_api_key — Fernet helpers
  AnthropicAdapter — fetches usage from api.anthropic.com/v1/usage
  OpenAIAdapter    — fetches usage from api.openai.com/v1/usage + billing
  sync_provider(provider_id) — upserts LLMUsageRecord rows for one provider
  sync_llm_usage() — Celery task; calls sync_provider for all active providers
"""
import base64
import datetime
import hashlib
import logging

import requests
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


# ── Encryption helpers ────────────────────────────────────────────────────────

def _get_fernet():
    from cryptography.fernet import Fernet
    key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt_api_key(raw: str) -> str:
    return _get_fernet().encrypt(raw.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()


# ── Provider adapters ─────────────────────────────────────────────────────────

class AnthropicAdapter:
    """
    Fetches daily usage from the Anthropic Admin API.

    Requires an Admin API key (sk-ant-admin...) — NOT a standard API key.
    Admin keys are created in: Console → Settings → Admin Keys
    Docs: https://docs.anthropic.com/en/api/usage-cost-api

    Makes two calls:
      /v1/organizations/usage_report/messages — token counts per model per day
      /v1/organizations/cost_report           — total USD cost (distributed proportionally)

    Returns a list of dicts with keys:
      date, provider, model, input_tokens, output_tokens,
      cache_creation_tokens, cache_read_tokens, request_count, cost_usd

    Note: request_count is always 0 — not available from this API.
    """
    USAGE_URL = "https://api.anthropic.com/v1/organizations/usage_report/messages"
    COST_URL = "https://api.anthropic.com/v1/organizations/cost_report"

    def fetch(self, api_key: str, since_date: datetime.date, until_date: datetime.date) -> list:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        # RFC 3339 datetimes required
        starting_at = f"{since_date.isoformat()}T00:00:00Z"
        ending_at = f"{(until_date + datetime.timedelta(days=1)).isoformat()}T00:00:00Z"

        # ── Fetch token usage (per model per day) ─────────────────────────────
        params: list = [
            ("starting_at", starting_at),
            ("ending_at", ending_at),
            ("bucket_width", "1d"),
            ("group_by[]", "model"),
            ("limit", 31),
        ]
        raw_buckets = []
        while True:
            resp = requests.get(self.USAGE_URL, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Anthropic usage API returned {resp.status_code}: {resp.text[:200]}"
                )
            body = resp.json()
            raw_buckets.extend(body.get("data", []))
            if not body.get("has_more", False):
                break
            next_page = body.get("next_page")
            if not next_page:
                break
            params = [(k, v) for k, v in params if k != "page"] + [("page", next_page)]

        # ── Fetch total cost for the date range ───────────────────────────────
        total_cost_usd = 0.0
        try:
            cost_resp = requests.get(
                self.COST_URL,
                headers=headers,
                params=[("starting_at", starting_at), ("ending_at", ending_at)],
                timeout=30,
            )
            if cost_resp.status_code == 200:
                for bucket in cost_resp.json().get("data", []):
                    for item in bucket.get("results", []):
                        # cost is in USD cents as a decimal string
                        total_cost_usd += float(item.get("cost", "0")) / 100.0
        except Exception as exc:
            logger.warning("Anthropic cost fetch failed: %s", exc)

        # ── Build records from usage buckets ──────────────────────────────────
        day_records = []
        for bucket in raw_buckets:
            try:
                day = datetime.date.fromisoformat(bucket["starting_at"][:10])
            except (ValueError, KeyError):
                continue
            for result in bucket.get("results", []):
                cache_obj = result.get("cache_creation") or {}
                cache_creation_tokens = (
                    int(cache_obj.get("ephemeral_1h_input_tokens", 0)) +
                    int(cache_obj.get("ephemeral_5m_input_tokens", 0))
                )
                cache_read = int(result.get("cache_read_input_tokens", 0))
                day_records.append({
                    "date": day,
                    "provider": "anthropic",
                    "model": result.get("model") or "unknown",
                    "input_tokens": int(result.get("uncached_input_tokens", 0)),
                    "output_tokens": int(result.get("output_tokens", 0)),
                    "cache_creation_tokens": cache_creation_tokens,
                    "cache_read_tokens": cache_read,
                    "request_count": 0,  # not available from Admin API
                    "cost_usd": 0.0,     # allocated below
                })

        # Distribute total cost proportionally by output tokens
        total_out = sum(r["output_tokens"] for r in day_records) or 1
        for r in day_records:
            r["cost_usd"] = round(total_cost_usd * (r["output_tokens"] / total_out), 6)

        return day_records


class OpenAIAdapter:
    """
    Fetches daily usage from https://api.openai.com/v1/usage (one call per day)
    and billing cost from https://api.openai.com/v1/dashboard/billing/usage.

    Returns a list of dicts with the same keys as AnthropicAdapter.fetch().
    cache_creation_tokens and cache_read_tokens are always 0 for OpenAI.
    """
    USAGE_URL = "https://api.openai.com/v1/usage"
    BILLING_URL = "https://api.openai.com/v1/dashboard/billing/usage"

    def fetch(self, api_key: str, since_date: datetime.date, until_date: datetime.date) -> list:
        headers = {"Authorization": f"Bearer {api_key}"}

        # Fetch billing cost for the full date range (total, in cents)
        billing_resp = requests.get(
            self.BILLING_URL,
            headers=headers,
            params={
                "start_date": since_date.isoformat(),
                "end_date": (until_date + datetime.timedelta(days=1)).isoformat(),
            },
            timeout=30,
        )
        billing_total_cents = 0.0
        if billing_resp.status_code == 200:
            billing_total_cents = float(billing_resp.json().get("total_usage", 0))

        # Iterate day-by-day (OpenAI usage endpoint takes a single date)
        day = since_date
        day_records: list = []
        while day <= until_date:
            usage_resp = requests.get(
                self.USAGE_URL,
                headers=headers,
                params={"date": day.isoformat()},
                timeout=30,
            )
            if usage_resp.status_code == 200:
                for item in usage_resp.json().get("data", []):
                    day_records.append({
                        "date": day,
                        "provider": "openai",
                        "model": item.get("snapshot_id", "unknown"),
                        "input_tokens": int(item.get("n_context_tokens_total", 0)),
                        "output_tokens": int(item.get("n_generated_tokens_total", 0)),
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "request_count": int(item.get("n_requests", 0)),
                        "cost_usd": 0.0,  # allocated below
                    })
            day += datetime.timedelta(days=1)

        # Allocate billing cost proportionally by output tokens
        total_out = sum(r["output_tokens"] for r in day_records) or 1
        total_cost_usd = billing_total_cents / 100.0
        for r in day_records:
            r["cost_usd"] = round(total_cost_usd * (r["output_tokens"] / total_out), 6)

        return day_records


ADAPTERS = {
    "anthropic": AnthropicAdapter,
    "openai": OpenAIAdapter,
}


# ── sync_provider ─────────────────────────────────────────────────────────────

def sync_provider(provider_id: str) -> int:
    """
    Sync LLM usage for one LLMProvider. Returns the number of records upserted.
    Raises if provider not found or adapter errors.
    """
    from django.utils import timezone
    from monitor.models import LLMProvider, LLMUsageRecord

    provider = LLMProvider.objects.select_related("organization").get(pk=provider_id)
    if not provider.is_active:
        return 0

    adapter_cls = ADAPTERS.get(provider.provider)
    if adapter_cls is None:
        raise ValueError(f"Unknown provider type: {provider.provider}")

    api_key = decrypt_api_key(provider.api_key_encrypted)
    today = datetime.date.today()
    since = today - datetime.timedelta(days=32)

    adapter = adapter_cls()
    raw_records = adapter.fetch(api_key, since, today)

    count = 0
    for r in raw_records:
        _, created = LLMUsageRecord.objects.update_or_create(
            date=r["date"],
            organization=provider.organization,
            provider=r["provider"],
            model=r["model"],
            defaults={
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "cache_creation_tokens": r["cache_creation_tokens"],
                "cache_read_tokens": r["cache_read_tokens"],
                "request_count": r["request_count"],
                "cost_usd": r["cost_usd"],
            },
        )
        count += 1

    provider.last_synced_at = timezone.now()
    provider.save(update_fields=["last_synced_at"])
    logger.info("sync_provider: %s wrote %d records", provider.label, count)
    return count


# ── Celery task ───────────────────────────────────────────────────────────────

@shared_task(name="monitor.sync_llm_usage")
def sync_llm_usage() -> int:
    from monitor.models import LLMProvider
    providers = list(LLMProvider.objects.filter(is_active=True).select_related("organization"))
    total = 0
    for p in providers:
        try:
            total += sync_provider(str(p.id))
        except Exception as exc:
            logger.warning("LLM sync failed for provider %s (%s): %s", p.label, p.provider, exc)
    logger.info("sync_llm_usage: total %d records across %d providers", total, len(providers))
    return total
