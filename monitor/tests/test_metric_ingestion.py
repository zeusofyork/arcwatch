"""
monitor/tests/test_metric_ingestion.py

Tests for the metric ingestion service.

The test database is SQLite in-memory (see settings.py TEST config).
The 0002 migration creates the gpu_metrics table in SQLite-compatible DDL,
so raw-SQL inserts and selects work without TimescaleDB.
"""
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from monitor.models import GPU, GPUCluster, GPUNode, Organization
from monitor.services.metric_ingestion import ingest_gpu_metrics


def _make_org(suffix=""):
    user = User.objects.create_user(username=f"user{suffix}", password="pw")
    org = Organization.objects.create(
        name=f"Org{suffix}", slug=f"org{suffix}", owner=user
    )
    return org


def _make_cluster(org, name="test-cluster"):
    return GPUCluster.objects.create(organization=org, name=name, cloud="on_prem")


def _sample_payload(node_name="gpu-node-01", gpu_uuid="GPU-aabbccdd"):
    return {
        "node_name": node_name,
        "gpu_type": "H100-SXM",
        "metrics": [
            {
                "gpu_uuid": gpu_uuid,
                "gpu_index": 0,
                "utilization": 85.0,
                "memory_used_mb": 65000,
                "memory_total_mb": 81920,
                "temperature": 72,
                "power_watts": 350,
                "sm_clock_mhz": 1410,
                "mem_clock_mhz": 1593,
                "pcie_tx_bytes": 1024,
                "pcie_rx_bytes": 512,
            }
        ],
    }


def _count_gpu_metrics(gpu_uuid):
    """Return the number of gpu_metrics rows for a given uuid."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM gpu_metrics WHERE gpu_uuid = %s", [gpu_uuid]
        )
        return cur.fetchone()[0]


class IngestCreatesNodeAndGPUTest(TestCase):
    """ingest_gpu_metrics creates GPUNode and GPU when they don't exist."""

    def setUp(self):
        self.org = _make_org("a")
        self.cluster = _make_cluster(self.org)

    def test_ingest_creates_node_and_gpu_if_missing(self):
        payload = _sample_payload(node_name="new-node", gpu_uuid="GPU-new-001")

        count = ingest_gpu_metrics(self.org, self.cluster, payload)

        self.assertEqual(count, 1, "Should have inserted 1 metric row")

        # GPUNode created
        node = GPUNode.objects.get(cluster=self.cluster, hostname="new-node")
        self.assertEqual(node.gpu_type, "H100-SXM")
        self.assertEqual(node.gpu_count, 1)

        # GPU created
        gpu = GPU.objects.get(uuid="GPU-new-001")
        self.assertEqual(gpu.node, node)
        self.assertEqual(gpu.current_utilization, 85.0)
        self.assertEqual(gpu.current_memory_used_mb, 65000)
        self.assertEqual(gpu.current_temperature_c, 72)

        # Raw hypertable row
        rows = _count_gpu_metrics("GPU-new-001")
        self.assertEqual(rows, 1)

    def test_hypertable_row_content(self):
        """Verify key column values in the inserted gpu_metrics row."""
        payload = _sample_payload(node_name="content-node", gpu_uuid="GPU-content-01")
        ingest_gpu_metrics(self.org, self.cluster, payload)

        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT gpu_uuid, node_name, utilization, memory_used_mb,
                       temperature, power_watts
                FROM gpu_metrics
                WHERE gpu_uuid = %s
                """,
                ["GPU-content-01"],
            )
            row = cur.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "GPU-content-01")
        self.assertEqual(row[1], "content-node")
        self.assertAlmostEqual(row[2], 85.0, places=1)
        self.assertEqual(row[3], 65000)
        self.assertEqual(row[4], 72)
        self.assertEqual(row[5], 350)


class IngestUpdatesExistingGPUTest(TestCase):
    """ingest_gpu_metrics updates an existing GPU's snapshot fields."""

    def setUp(self):
        self.org = _make_org("b")
        self.cluster = _make_cluster(self.org)
        # First ingest to create the records
        ingest_gpu_metrics(
            self.org,
            self.cluster,
            _sample_payload(node_name="worker-01", gpu_uuid="GPU-existing-01"),
        )

    def test_ingest_updates_existing_gpu(self):
        updated_payload = {
            "node_name": "worker-01",
            "gpu_type": "H100-SXM",
            "metrics": [
                {
                    "gpu_uuid": "GPU-existing-01",
                    "gpu_index": 0,
                    "utilization": 42.0,
                    "memory_used_mb": 32000,
                    "memory_total_mb": 81920,
                    "temperature": 55,
                    "power_watts": 200,
                    "sm_clock_mhz": 900,
                    "mem_clock_mhz": 1200,
                }
            ],
        }

        count = ingest_gpu_metrics(self.org, self.cluster, updated_payload)
        self.assertEqual(count, 1)

        gpu = GPU.objects.get(uuid="GPU-existing-01")
        self.assertAlmostEqual(gpu.current_utilization, 42.0, places=1)
        self.assertEqual(gpu.current_memory_used_mb, 32000)
        self.assertEqual(gpu.current_temperature_c, 55)
        self.assertEqual(gpu.current_power_watts, 200)

        # Both ingest calls should have appended rows
        rows = _count_gpu_metrics("GPU-existing-01")
        self.assertEqual(rows, 2, "Both ingests should have appended a row")
