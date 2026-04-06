"""monitor/models/llm.py — LLM provider API key registry and daily usage records."""
import uuid
from django.db import models
from .organization import Organization


class LLMProvider(models.Model):
    PROVIDER_CHOICES = [
        ("anthropic", "Anthropic"),
        ("openai", "OpenAI"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="llm_providers"
    )
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)
    label = models.CharField(max_length=100, help_text="Human name, e.g. 'Production Key'")
    api_key_encrypted = models.TextField(help_text="Fernet-encrypted API key")
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "LLM Provider"
        indexes = [
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self):
        return f"{self.get_provider_display()} — {self.label}"

    @property
    def api_key_masked(self):
        """Return a masked display string for the UI."""
        from monitor.services.llm_sync_engine import decrypt_api_key
        try:
            raw = decrypt_api_key(self.api_key_encrypted)
            return raw[:8] + "•" * 12 if len(raw) > 8 else "•" * len(raw)
        except Exception:
            return "•••••••••••••••••••"


class LLMUsageRecord(models.Model):
    date = models.DateField(help_text="Calendar day (UTC) this record covers")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="llm_usage_records"
    )
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=200)
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    cache_creation_tokens = models.BigIntegerField(default=0)
    cache_read_tokens = models.BigIntegerField(default=0)
    request_count = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    class Meta:
        unique_together = [("date", "organization", "provider", "model")]
        ordering = ["-date", "provider", "model"]
        verbose_name = "LLM Usage Record"
        indexes = [
            models.Index(fields=["organization", "date"]),
        ]

    def __str__(self):
        return f"{self.date} {self.provider}/{self.model} ${self.cost_usd}"
