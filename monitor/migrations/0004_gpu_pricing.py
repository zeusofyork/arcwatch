"""
monitor/migrations/0004_gpu_pricing.py

Creates the GPUPricing Django ORM model table.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0003_inference_hypertable'),
    ]

    operations = [
        migrations.CreateModel(
            name='GPUPricing',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gpu_model_pattern', models.CharField(
                    max_length=128,
                    help_text='Case-insensitive substring matched against GPU model name (e.g. "H100", "A100")',
                )),
                ('hourly_rate', models.DecimalField(
                    max_digits=8, decimal_places=4,
                    help_text='Per-GPU hourly cost in USD',
                )),
                ('provider', models.CharField(max_length=64, blank=True, default='')),
                ('pricing_type', models.CharField(
                    max_length=16,
                    choices=[
                        ('on_demand', 'On-Demand'),
                        ('reserved', 'Reserved'),
                        ('spot', 'Spot'),
                    ],
                    default='on_demand',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'GPU Pricing',
                'verbose_name_plural': 'GPU Pricing',
                'ordering': ['-hourly_rate'],
            },
        ),
    ]
