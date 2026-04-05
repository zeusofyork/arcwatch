"""
monitor/migrations/0002_create_hypertables.py

Creates the gpu_metrics TimescaleDB hypertable.
This is a raw-SQL migration — no Django model is created.
When running against SQLite (e.g. in-memory test DB), the TimescaleDB-specific
statements are skipped gracefully.
"""
from django.db import migrations


CREATE_GPU_METRICS = """
CREATE TABLE IF NOT EXISTS gpu_metrics (
    time            TIMESTAMPTZ NOT NULL,
    gpu_uuid        VARCHAR(64) NOT NULL,
    node_name       VARCHAR(255) NOT NULL,
    utilization     REAL,
    memory_used_mb  INTEGER,
    memory_total_mb INTEGER,
    temperature     INTEGER,
    power_watts     INTEGER,
    sm_clock_mhz    INTEGER,
    mem_clock_mhz   INTEGER,
    pcie_tx_bytes   BIGINT DEFAULT 0,
    pcie_rx_bytes   BIGINT DEFAULT 0,
    ecc_single      INTEGER DEFAULT 0,
    ecc_double      INTEGER DEFAULT 0
);
"""

CREATE_HYPERTABLE = """
SELECT create_hypertable('gpu_metrics', 'time', if_not_exists => TRUE);
"""

CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_gpu_metrics_uuid_time
    ON gpu_metrics (gpu_uuid, time DESC);
"""

DROP_GPU_METRICS = """
DROP TABLE IF EXISTS gpu_metrics;
"""


def apply_timescale(apps, schema_editor):
    """Create gpu_metrics and convert it to a TimescaleDB hypertable."""
    connection = schema_editor.connection
    db_engine = connection.settings_dict.get('ENGINE', '')

    if 'sqlite' in db_engine:
        # SQLite (used in unit tests): create a simplified compatible table
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gpu_metrics (
                    time            TEXT NOT NULL,
                    gpu_uuid        VARCHAR(64) NOT NULL,
                    node_name       VARCHAR(255) NOT NULL,
                    utilization     REAL,
                    memory_used_mb  INTEGER,
                    memory_total_mb INTEGER,
                    temperature     INTEGER,
                    power_watts     INTEGER,
                    sm_clock_mhz    INTEGER,
                    mem_clock_mhz   INTEGER,
                    pcie_tx_bytes   INTEGER DEFAULT 0,
                    pcie_rx_bytes   INTEGER DEFAULT 0,
                    ecc_single      INTEGER DEFAULT 0,
                    ecc_double      INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_gpu_metrics_uuid_time
                    ON gpu_metrics (gpu_uuid, time DESC)
            """)
        return

    # PostgreSQL / TimescaleDB path
    with connection.cursor() as cur:
        cur.execute(CREATE_GPU_METRICS)
        cur.execute(CREATE_HYPERTABLE)
        cur.execute(CREATE_INDEX)


def revert_timescale(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cur:
        cur.execute(DROP_GPU_METRICS)


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(apply_timescale, revert_timescale),
    ]
