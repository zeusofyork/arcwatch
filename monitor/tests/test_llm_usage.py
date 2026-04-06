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
        self.assertIn("OpenAI", str(p))
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


class EncryptionTest(TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        from monitor.services.llm_sync_engine import encrypt_api_key, decrypt_api_key
        raw = "sk-ant-api03-abc123xyz"
        encrypted = encrypt_api_key(raw)
        self.assertNotEqual(encrypted, raw)
        self.assertEqual(decrypt_api_key(encrypted), raw)

    def test_same_plaintext_produces_different_ciphertext(self):
        from monitor.services.llm_sync_engine import encrypt_api_key
        # Fernet uses a random IV, so same plaintext → different ciphertext each time
        e1 = encrypt_api_key("same-key")
        e2 = encrypt_api_key("same-key")
        self.assertNotEqual(e1, e2)


class AnthropicAdapterTest(TestCase):
    def test_fetch_returns_records(self):
        from unittest.mock import patch, MagicMock
        import datetime
        from monitor.services.llm_sync_engine import AnthropicAdapter

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "model": "claude-3-5-sonnet-20241022",
                    "usage_period": {"start_time": "2026-04-01T00:00:00Z"},
                    "input_tokens": 100000,
                    "output_tokens": 5000,
                    "cache_creation_input_tokens": 2000,
                    "cache_read_input_tokens": 80000,
                    "request_count": 42,
                    "cost": 1.23456,
                }
            ],
            "has_more": False,
        }

        with patch("monitor.services.llm_sync_engine.requests.get", return_value=mock_response):
            adapter = AnthropicAdapter()
            records = adapter.fetch(
                "sk-ant-fake",
                datetime.date(2026, 4, 1),
                datetime.date(2026, 4, 2),
            )

        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r["model"], "claude-3-5-sonnet-20241022")
        self.assertEqual(r["date"], datetime.date(2026, 4, 1))
        self.assertEqual(r["input_tokens"], 100000)
        self.assertEqual(r["output_tokens"], 5000)
        self.assertEqual(r["cache_creation_tokens"], 2000)
        self.assertEqual(r["cache_read_tokens"], 80000)
        self.assertEqual(r["request_count"], 42)
        self.assertEqual(r["provider"], "anthropic")
        self.assertAlmostEqual(float(r["cost_usd"]), 1.23456, places=4)

    def test_fetch_raises_on_auth_error(self):
        from unittest.mock import patch, MagicMock
        import datetime
        from monitor.services.llm_sync_engine import AnthropicAdapter

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("monitor.services.llm_sync_engine.requests.get", return_value=mock_response):
            adapter = AnthropicAdapter()
            with self.assertRaises(RuntimeError):
                adapter.fetch("bad-key", datetime.date(2026, 4, 1), datetime.date(2026, 4, 2))


class OpenAIAdapterTest(TestCase):
    def test_fetch_returns_records(self):
        from unittest.mock import patch, MagicMock
        import datetime
        from monitor.services.llm_sync_engine import OpenAIAdapter

        usage_response = MagicMock()
        usage_response.status_code = 200
        usage_response.json.return_value = {
            "data": [
                {
                    "snapshot_id": "gpt-4o-2024-11-20",
                    "n_requests": 10,
                    "n_context_tokens_total": 50000,
                    "n_generated_tokens_total": 3000,
                }
            ]
        }

        billing_response = MagicMock()
        billing_response.status_code = 200
        billing_response.json.return_value = {"total_usage": 250}  # in cents

        with patch("monitor.services.llm_sync_engine.requests.get",
                   side_effect=[billing_response, usage_response]):
            adapter = OpenAIAdapter()
            records = adapter.fetch(
                "sk-fake",
                datetime.date(2026, 4, 1),
                datetime.date(2026, 4, 1),
            )

        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r["model"], "gpt-4o-2024-11-20")
        self.assertEqual(r["date"], datetime.date(2026, 4, 1))
        self.assertEqual(r["input_tokens"], 50000)
        self.assertEqual(r["output_tokens"], 3000)
        self.assertEqual(r["request_count"], 10)
        self.assertEqual(r["cache_creation_tokens"], 0)
        self.assertEqual(r["cache_read_tokens"], 0)
        self.assertEqual(r["provider"], "openai")
        self.assertAlmostEqual(r["cost_usd"], 2.50, places=4)


class SyncProviderTest(TestCase):
    def setUp(self):
        self.org = _make_org("sync")
        from monitor.services.llm_sync_engine import encrypt_api_key
        self.provider = LLMProvider.objects.create(
            organization=self.org,
            provider="anthropic",
            label="Test Key",
            api_key_encrypted=encrypt_api_key("sk-ant-fake-key"),
        )

    def _mock_anthropic_response(self, day_str="2026-04-01"):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "data": [{
                "model": "claude-3-5-sonnet-20241022",
                "usage_period": {"start_time": f"{day_str}T00:00:00Z"},
                "input_tokens": 1000,
                "output_tokens": 200,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 500,
                "request_count": 5,
                "cost": 0.05,
            }],
            "has_more": False,
        }
        return resp

    def test_sync_provider_writes_records(self):
        from unittest.mock import patch
        from monitor.services.llm_sync_engine import sync_provider
        with patch("monitor.services.llm_sync_engine.requests.get",
                   return_value=self._mock_anthropic_response()):
            count = sync_provider(str(self.provider.id))
        self.assertEqual(count, 1)
        self.assertEqual(LLMUsageRecord.objects.filter(organization=self.org).count(), 1)
        record = LLMUsageRecord.objects.get(organization=self.org)
        self.assertEqual(record.model, "claude-3-5-sonnet-20241022")
        self.assertEqual(record.input_tokens, 1000)

    def test_sync_provider_is_idempotent(self):
        from unittest.mock import patch
        from monitor.services.llm_sync_engine import sync_provider
        with patch("monitor.services.llm_sync_engine.requests.get",
                   return_value=self._mock_anthropic_response()):
            c1 = sync_provider(str(self.provider.id))
        with patch("monitor.services.llm_sync_engine.requests.get",
                   return_value=self._mock_anthropic_response()):
            c2 = sync_provider(str(self.provider.id))
        self.assertGreaterEqual(c1, 1)
        self.assertGreaterEqual(c2, 1)
        # Same record updated, not duplicated
        self.assertEqual(LLMUsageRecord.objects.filter(organization=self.org).count(), 1)

    def test_sync_provider_updates_last_synced_at(self):
        from unittest.mock import patch
        from monitor.services.llm_sync_engine import sync_provider
        self.assertIsNone(self.provider.last_synced_at)
        with patch("monitor.services.llm_sync_engine.requests.get",
                   return_value=self._mock_anthropic_response()):
            sync_provider(str(self.provider.id))
        self.provider.refresh_from_db()
        self.assertIsNotNone(self.provider.last_synced_at)

    def test_sync_provider_skips_inactive(self):
        from unittest.mock import patch
        from monitor.services.llm_sync_engine import sync_provider
        self.provider.is_active = False
        self.provider.save()
        with patch("monitor.services.llm_sync_engine.requests.get") as mock_get:
            count = sync_provider(str(self.provider.id))
        mock_get.assert_not_called()
        self.assertEqual(count, 0)
