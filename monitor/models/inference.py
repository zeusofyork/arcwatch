"""
monitor/models/inference.py -- Inference serving endpoints and deployed models.
"""
import uuid

from django.db import models
from django.utils import timezone

from .base import TenantManager


class InferenceEndpoint(models.Model):
    """
    A vLLM / TGI / Triton / Ollama serving endpoint.
    Discovered from agent's vLLM scraper or manually configured.
    """
    ENGINE_CHOICES = [
        ('vllm', 'vLLM'),
        ('tgi', 'Text Generation Inference'),
        ('triton', 'Triton Inference Server'),
        ('ollama', 'Ollama'),
        ('custom', 'Custom'),
    ]

    STATUS_CHOICES = [
        ('serving', 'Serving'),
        ('loading', 'Loading'),
        ('idle', 'Idle'),
        ('error', 'Error'),
        ('offline', 'Offline'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Tenant / ownership
    organization = models.ForeignKey(
        'monitor.Organization', on_delete=models.CASCADE,
        related_name='inference_endpoints', db_index=True,
    )
    team = models.ForeignKey(
        'monitor.Team', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='inference_endpoints',
    )

    # Identity
    name = models.CharField(max_length=255)
    engine = models.CharField(
        max_length=20, choices=ENGINE_CHOICES, default='vllm',
    )
    url = models.URLField(max_length=500, blank=True, default='',
                          help_text='Metrics/API endpoint URL')

    # Model config
    current_model = models.CharField(max_length=255, blank=True, default='')
    quantization = models.CharField(max_length=64, blank=True, default='')
    max_batch_size = models.IntegerField(null=True, blank=True)

    # Current live metrics (denormalized snapshot updated on each scrape)
    current_requests_per_sec = models.FloatField(null=True, blank=True)
    current_tokens_per_sec = models.FloatField(null=True, blank=True)
    current_avg_latency_ms = models.FloatField(null=True, blank=True)
    current_p99_latency_ms = models.FloatField(null=True, blank=True)
    current_queue_depth = models.IntegerField(null=True, blank=True)
    current_kv_cache_usage_pct = models.FloatField(null=True, blank=True)
    current_batch_utilization = models.FloatField(null=True, blank=True)

    # Lifecycle
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default='idle', db_index=True,
    )
    last_seen = models.DateTimeField(default=timezone.now, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    labels = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()
    objects_unscoped = models.Manager()

    class Meta:
        ordering = ['name']
        unique_together = [('organization', 'name')]
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['organization', 'status']),
        ]

    def __str__(self):
        return f"{self.name} ({self.engine})"
