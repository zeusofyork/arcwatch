"""monitor/tests/test_llm_usage.py — Tests for LLM usage tracking."""
import datetime
from django.contrib.auth.models import User
from django.test import TestCase
from monitor.models import Organization, LLMProvider, LLMUsageRecord


def _make_org(slug="testorg"):
    user = User.objects.create_user(username=f"u-{slug}", password="pw")
    return Organization.objects.create(name=slug, slug=slug, owner=user)


class LLMProviderModelTest(TestCase):
    def setUp(self):
        self.org = _make_org("prov")

    def test_create_provider(self):
        p = LLMProvider.objects.create(
            organization=self.org,
            provider="anthropic",
            label="Prod Key",
            api_key_encrypted="encrypted-placeholder",
        )
        self.assertEqual(p.provider, "anthropic")
        self.assertTrue(p.is_active)
        self.assertIsNone(p.last_synced_at)

    def test_provider_str(self):
        p = LLMProvider(organization=self.org, provider="openai", label="My Key")
        self.assertIn("openai", str(p))
        self.assertIn("My Key", str(p))


class LLMUsageRecordModelTest(TestCase):
    def setUp(self):
        self.org = _make_org("usage")

    def test_create_usage_record(self):
        r = LLMUsageRecord.objects.create(
            date=datetime.date(2026, 4, 1),
            organization=self.org,
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            input_tokens=100000,
            output_tokens=5000,
            cache_creation_tokens=2000,
            cache_read_tokens=80000,
            request_count=42,
            cost_usd="1.234567",
        )
        self.assertEqual(r.request_count, 42)
        self.assertEqual(float(r.cost_usd), 1.234567)

    def test_unique_together_prevents_duplicate(self):
        from django.db import IntegrityError
        kwargs = dict(
            date=datetime.date(2026, 4, 1),
            organization=self.org,
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            input_tokens=1, output_tokens=1,
            cache_creation_tokens=0, cache_read_tokens=0,
            request_count=1, cost_usd="0.001",
        )
        LLMUsageRecord.objects.create(**kwargs)
        with self.assertRaises(IntegrityError):
            LLMUsageRecord.objects.create(**kwargs)
