import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0010_llm_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClaudeCodeUsageRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(help_text="Calendar day (UTC) this record covers")),
                ("organization", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="claude_code_records",
                    to="monitor.organization",
                )),
                ("user_email", models.CharField(max_length=254)),
                ("customer_type", models.CharField(
                    default="api", max_length=32,
                    help_text="'api' = pay-as-you-go, 'subscription' = Pro/Max plan",
                )),
                ("sessions", models.IntegerField(default=0)),
                ("lines_added", models.IntegerField(default=0)),
                ("lines_removed", models.IntegerField(default=0)),
                ("commits", models.IntegerField(default=0)),
                ("prs", models.IntegerField(default=0)),
                ("input_tokens", models.BigIntegerField(default=0)),
                ("output_tokens", models.BigIntegerField(default=0)),
                ("cache_read_tokens", models.BigIntegerField(default=0)),
                ("cost_usd", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
            ],
            options={
                "verbose_name": "Claude Code Usage Record",
                "ordering": ["-date", "user_email"],
            },
        ),
        migrations.AlterUniqueTogether(
            name="claudecodeusagerecord",
            unique_together={("date", "organization", "user_email")},
        ),
        migrations.AddIndex(
            model_name="claudecodeusagerecord",
            index=models.Index(
                fields=["organization", "date"],
                name="monitor_cc_organiz_date_idx",
            ),
        ),
    ]
