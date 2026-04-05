"""
monitor/models/cost.py -- GPU pricing reference table for cost attribution.
"""
from django.db import models


class GPUPricing(models.Model):
    """
    A pricing entry that maps a GPU model pattern to an hourly rate.

    gpu_model_pattern is matched case-insensitively against the GPU's
    current_model_name / gpu_type field using a LIKE/ILIKE query.
    Examples: "H100", "A100", "A10G", "RTX 4090"
    """
    PRICING_TYPE_CHOICES = [
        ('on_demand', 'On-Demand'),
        ('reserved', 'Reserved'),
        ('spot', 'Spot'),
    ]

    gpu_model_pattern = models.CharField(
        max_length=128,
        help_text='Case-insensitive substring matched against GPU model name (e.g. "H100", "A100")',
    )
    hourly_rate = models.DecimalField(
        max_digits=8, decimal_places=4,
        help_text='Per-GPU hourly cost in USD',
    )
    provider = models.CharField(max_length=64, blank=True, default='')
    pricing_type = models.CharField(
        max_length=16, choices=PRICING_TYPE_CHOICES, default='on_demand',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-hourly_rate']
        verbose_name = 'GPU Pricing'
        verbose_name_plural = 'GPU Pricing'

    def __str__(self):
        return f"{self.gpu_model_pattern} @ ${self.hourly_rate}/hr ({self.pricing_type})"
