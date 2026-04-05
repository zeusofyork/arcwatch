"""
monitor/migrations/0003_inference_hypertable.py

Creates the inference_metrics TimescaleDB hypertable.
Raw-SQL migration — no Django model is created for this hypertable.
When running against SQLite (unit tests) the TimescaleDB-specific calls
are skipped gracefully.
"""
from django.db import migrations


CREATE_INFERENCE_METRICS = """
CREATE TABLE IF NOT EXISTS inference_metrics (
    time                    TIMESTAMPTZ NOT NULL,
    endpoint_id             INTEGER NOT NULL,
    model_name              VARCHAR(255),
    requests_running        INTEGER,
    requests_waiting        INTEGER,
    prompt_throughput       REAL,
    generation_throughput   REAL,
    gpu_cache_usage         REAL,
    cpu_cache_usage         REAL,
    latency_p50             REAL,
    latency_p95             REAL,
    latency_p99             REAL,
    ttft_p50                REAL,
    ttft_p95                REAL,
    ttft_p99                REAL,
    tpot_avg                REAL,
    preemptions_total       INTEGER,
    batch_size_avg          REAL
);
"""

CREATE_HYPERTABLE = """
SELECT create_hypertable('inference_metrics', 'time', if_not_exists => TRUE);
"""

CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_inf_metrics_ep_time
    ON inference_metrics (endpoint_id, time DESC);
"""

DROP_INFERENCE_METRICS = """
DROP TABLE IF EXISTS inference_metrics;
"""


def apply_inference_hypertable(apps, schema_editor):
    """Create inference_metrics and convert to a TimescaleDB hypertable."""
    connection = schema_editor.connection
    db_engine = connection.settings_dict.get('ENGINE', '')

    if 'sqlite' in db_engine:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inference_metrics (
                    time                    TEXT NOT NULL,
                    endpoint_id             INTEGER NOT NULL,
                    model_name              VARCHAR(255),
                    requests_running        INTEGER,
                    requests_waiting        INTEGER,
                    prompt_throughput       REAL,
                    generation_throughput   REAL,
                    gpu_cache_usage         REAL,
                    cpu_cache_usage         REAL,
                    latency_p50             REAL,
                    latency_p95             REAL,
                    latency_p99             REAL,
                    ttft_p50                REAL,
                    ttft_p95                REAL,
                    ttft_p99                REAL,
                    tpot_avg                REAL,
                    preemptions_total       INTEGER,
                    batch_size_avg          REAL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_inf_metrics_ep_time
                    ON inference_metrics (endpoint_id, time DESC)
            """)
        return

    # PostgreSQL / TimescaleDB path
    with connection.cursor() as cur:
        cur.execute(CREATE_INFERENCE_METRICS)
        cur.execute(CREATE_HYPERTABLE)
        cur.execute(CREATE_INDEX)


def revert_inference_hypertable(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cur:
        cur.execute(DROP_INFERENCE_METRICS)


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0002_create_hypertables'),
    ]

    operations = [
        migrations.RunPython(apply_inference_hypertable, revert_inference_hypertable),
    ]
