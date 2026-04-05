"""
monitor/models/inference.py -- Inference serving endpoints and deployed models.

Stub for Task 3-4. Full implementation in Task 6-7.
"""
import uuid

from django.db import models

from .base import TenantManager


class InferenceEndpoint(models.Model):
    """
    A vLLM / TGI / Triton serving endpoint.
    Discovered from agent's vLLM scraper or manually configured.
    """
    FRAMEWORK_CHOICES = [
        ('vllm', 'vLLM'),
        ('tgi', 'Text Generation Inference'),
        ('triton', 'Triton Inference Server'),
        ('trt-llm', 'TensorRT-LLM'),
        ('custom', 'Custom'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'monitor.Organization', on_delete=models.CASCADE,
        related_name='inference_endpoints', db_index=True,
    )
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=500, help_text='Metrics endpoint URL')
    framework = models.CharField(
        max_length=20, choices=FRAMEWORK_CHOICES, default='vllm',
    )
    is_active = models.BooleanField(default=True, db_index=True)
    last_scraped = models.DateTimeField(null=True, blank=True)
    labels = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()
    objects_unscoped = models.Manager()

    class Meta:
        ordering = ['name']
        unique_together = [('organization', 'name')]
        indexes = [
            models.Index(fields=['organization', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.framework})"
