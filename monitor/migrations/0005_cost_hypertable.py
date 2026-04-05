"""
monitor/migrations/0005_cost_hypertable.py

Creates the cost_snapshots TimescaleDB hypertable.
Raw-SQL migration — no Django model is created for this hypertable.
When running against SQLite (unit tests) the TimescaleDB-specific calls
are skipped gracefully.
"""
from django.db import migrations


CREATE_COST_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS cost_snapshots (
    time                TIMESTAMPTZ NOT NULL,
    gpu_uuid            VARCHAR(64) NOT NULL,
    endpoint_id         INTEGER,
    model_name          VARCHAR(255),
    hourly_rate         REAL,
    utilization         REAL,
    cost_this_period    REAL,
    waste_this_period   REAL
);
"""

CREATE_HYPERTABLE = """
SELECT create_hypertable('cost_snapshots', 'time', if_not_exists => TRUE);
"""

CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_cost_model_time
    ON cost_snapshots (model_name, time DESC);
"""

DROP_COST_SNAPSHOTS = """
DROP TABLE IF EXISTS cost_snapshots;
"""


def apply_cost_hypertable(apps, schema_editor):
    """Create cost_snapshots and convert to a TimescaleDB hypertable."""
    connection = schema_editor.connection
    db_engine = connection.settings_dict.get('ENGINE', '')

    if 'sqlite' in db_engine:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cost_snapshots (
                    time                TEXT NOT NULL,
                    gpu_uuid            VARCHAR(64) NOT NULL,
                    endpoint_id         INTEGER,
                    model_name          VARCHAR(255),
                    hourly_rate         REAL,
                    utilization         REAL,
                    cost_this_period    REAL,
                    waste_this_period   REAL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_cost_model_time
                    ON cost_snapshots (model_name, time DESC)
            """)
        return

    # PostgreSQL / TimescaleDB path
    with connection.cursor() as cur:
        cur.execute(CREATE_COST_SNAPSHOTS)
        cur.execute(CREATE_HYPERTABLE)
        cur.execute(CREATE_INDEX)


def revert_cost_hypertable(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cur:
        cur.execute(DROP_COST_SNAPSHOTS)


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0004_gpu_pricing'),
    ]

    operations = [
        migrations.RunPython(apply_cost_hypertable, revert_cost_hypertable),
    ]
