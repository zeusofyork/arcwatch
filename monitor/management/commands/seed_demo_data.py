"""
monitor/management/commands/seed_demo_data.py

Management command to seed demo GPU data into the database.

Usage:
    python manage.py seed_demo_data --nodes 4 --gpus-per-node 4 --hours 6
"""
import math
import random
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from monitor.models import GPU, GPUCluster, GPUNode, Organization


MODELS = [
    "Llama-3.1-70B",
    "Mistral-7B",
    "Qwen2.5-72B",
    "DeepSeek-V3",
]

GPU_TYPES = [
    ("NVIDIA H100-SXM5-80GB", 80),
    ("NVIDIA A100-SXM4-80GB", 80),
    ("NVIDIA A100-SXM4-40GB", 40),
    ("NVIDIA H100-PCIe-80GB", 80),
]

INSTANCE_TYPES = [
    ("p4d.24xlarge", 32.77),
    ("p3.16xlarge", 24.48),
    ("a3-highgpu-8g", 29.39),
    ("Standard_ND96asr_v4", 27.20),
]


def _business_hour_factor(dt):
    """
    Return a utilization multiplier based on time-of-day.
    Higher during business hours (08:00-20:00 UTC), lower at night.
    """
    hour = dt.hour + dt.minute / 60.0
    # Smooth cosine curve centred at 14:00 UTC (2pm)
    angle = math.pi * (hour - 2) / 12
    return 0.40 + 0.60 * max(0.0, math.sin(angle))


class Command(BaseCommand):
    help = "Seed demo GPU telemetry data for development and demos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--nodes",
            type=int,
            default=4,
            help="Number of GPU nodes to create (default: 4)",
        )
        parser.add_argument(
            "--gpus-per-node",
            type=int,
            default=4,
            help="Number of GPUs per node (default: 4)",
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=6,
            help="Hours of historical metrics to generate (default: 6)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            default=False,
            help="Delete existing demo data before seeding",
        )

    def handle(self, *args, **options):
        node_count = options["nodes"]
        gpus_per_node = options["gpus_per_node"]
        hours = options["hours"]
        clear = options["clear"]

        if node_count < 1 or node_count > 32:
            raise CommandError("--nodes must be between 1 and 32")
        if gpus_per_node < 1 or gpus_per_node > 16:
            raise CommandError("--gpus-per-node must be between 1 and 16")
        if hours < 1 or hours > 720:
            raise CommandError("--hours must be between 1 and 720")

        self.stdout.write(self.style.MIGRATE_HEADING("GPUWatch Demo Data Seeder"))
        self.stdout.write(
            f"  nodes={node_count}  gpus/node={gpus_per_node}  hours={hours}"
        )

        # ── 1. Demo user + org ────────────────────────────────────────────────
        demo_user, user_created = User.objects.get_or_create(
            username="demo",
            defaults={"email": "demo@gpuwatch.dev", "is_staff": False},
        )
        if user_created:
            demo_user.set_password("demo")
            demo_user.save()
            self.stdout.write(self.style.SUCCESS("  Created user: demo / demo"))
        else:
            self.stdout.write("  User 'demo' already exists")

        org, org_created = Organization.objects.get_or_create(
            slug="demo-org",
            defaults={
                "name": "Demo Organization",
                "owner": demo_user,
                "plan": "pro",
            },
        )
        if org_created:
            self.stdout.write(self.style.SUCCESS(f"  Created org: {org.name}"))
        else:
            self.stdout.write(f"  Org '{org.name}' already exists")

        # ── 2. GPUCluster ─────────────────────────────────────────────────────
        cluster, cluster_created = GPUCluster.objects.get_or_create(
            organization=org,
            name="demo-cluster",
            defaults={
                "cloud": "aws",
                "region": "us-east-1",
                "k8s_context": "demo-k8s",
            },
        )
        if cluster_created:
            self.stdout.write(self.style.SUCCESS(f"  Created cluster: {cluster.name}"))
        else:
            self.stdout.write(f"  Cluster '{cluster.name}' already exists")

        # ── 3. Optionally clear existing demo metrics ─────────────────────────
        if clear:
            with connection.cursor() as cur:
                # Get UUIDs of all demo GPUs before deleting so we can wipe metrics
                cur.execute(
                    "DELETE FROM gpu_metrics WHERE node_name LIKE 'demo-node-%'"
                )
                deleted = cur.rowcount
            self.stdout.write(
                self.style.WARNING(f"  Cleared {deleted} existing metric rows")
            )
            GPUNode.objects_unscoped.filter(cluster=cluster).delete()
            self.stdout.write(self.style.WARNING("  Cleared existing demo nodes/GPUs"))

        # ── 4. Build nodes + GPUs ─────────────────────────────────────────────
        gpu_type_name, vram_gb = random.choice(GPU_TYPES)
        instance_type, hourly_cost = random.choice(INSTANCE_TYPES)
        memory_total_mb = vram_gb * 1024

        nodes = []
        all_gpus = []  # list of (GPU model, base_util, gpu_uuid, node_hostname, gpu_index)

        for n in range(node_count):
            hostname = f"demo-node-{n:02d}"
            node, _ = GPUNode.objects.get_or_create(
                organization=org,
                hostname=hostname,
                defaults={
                    "cluster": cluster,
                    "instance_type": instance_type,
                    "gpu_count": gpus_per_node,
                    "gpu_type": gpu_type_name,
                    "gpu_memory_gb": vram_gb,
                    "hourly_cost": round(hourly_cost + random.uniform(-2, 2), 4),
                    "status": "active",
                },
            )
            nodes.append(node)

            for g in range(gpus_per_node):
                gpu_uuid = f"GPU-demo-{n:02d}-{g:02d}-{uuid.uuid4().hex[:8]}"
                model_name = random.choice(MODELS)
                base_util = random.uniform(20, 85)  # per-GPU baseline

                gpu, _ = GPU.objects.get_or_create(
                    node=node,
                    gpu_index=g,
                    defaults={
                        "organization": org,
                        "uuid": gpu_uuid,
                        "current_utilization": base_util,
                        "current_memory_used_mb": int(memory_total_mb * base_util / 100),
                        "current_memory_total_mb": memory_total_mb,
                        "current_temperature_c": int(30 + base_util * 0.6),
                        "current_power_watts": round(50 + base_util * 3.5, 1),
                        "current_model_name": model_name,
                        "status": "healthy",
                    },
                )
                # Use stored UUID (may be different if GPU already existed)
                all_gpus.append((gpu.uuid, node.hostname, g, base_util, model_name))

        total_gpus = len(all_gpus)
        self.stdout.write(
            self.style.SUCCESS(
                f"  Upserted {len(nodes)} nodes × {gpus_per_node} GPUs = {total_gpus} GPU records"
            )
        )

        # ── 5. Generate historical metrics ────────────────────────────────────
        self.stdout.write(f"  Generating {hours}h of metrics at 1-min resolution…")

        now = timezone.now().replace(second=0, microsecond=0)
        total_minutes = hours * 60
        batch_size = 10_000

        insert_sql = """
            INSERT INTO gpu_metrics (
                time, gpu_uuid, node_name,
                utilization, memory_used_mb, memory_total_mb,
                temperature, power_watts, sm_clock_mhz, mem_clock_mhz,
                pcie_tx_bytes, pcie_rx_bytes, ecc_single, ecc_double
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """

        rows_buffer = []
        total_inserted = 0

        for minute_offset in range(total_minutes, 0, -1):
            ts = now - timedelta(minutes=minute_offset)
            bh_factor = _business_hour_factor(ts)
            ts_str = ts.isoformat()

            for gpu_uuid, node_name, gpu_index, base_util, model_name in all_gpus:
                # Utilization: base × business-hour factor + noise
                util = max(
                    0.0,
                    min(
                        100.0,
                        base_util * bh_factor + random.gauss(0, 5),
                    ),
                )
                mem_used = int(memory_total_mb * util / 100 * random.uniform(0.9, 1.1))
                mem_used = max(512, min(memory_total_mb, mem_used))

                temp = int(28 + util * 0.62 + random.uniform(-2, 2))
                power = round(45 + util * 3.6 + random.gauss(0, 8), 1)
                power = max(30.0, min(400.0, power))

                sm_clock = int(900 + util * 4.5)
                mem_clock = random.choice([877, 1215, 1593])

                rows_buffer.append((
                    ts_str,
                    gpu_uuid,
                    node_name,
                    round(util, 2),
                    mem_used,
                    memory_total_mb,
                    temp,
                    power,
                    sm_clock,
                    mem_clock,
                    random.randint(0, 200_000_000),  # pcie_tx_bytes
                    random.randint(0, 100_000_000),  # pcie_rx_bytes
                    0,  # ecc_single
                    0,  # ecc_double
                ))

                if len(rows_buffer) >= batch_size:
                    with connection.cursor() as cur:
                        cur.executemany(insert_sql, rows_buffer)
                    total_inserted += len(rows_buffer)
                    rows_buffer = []
                    self.stdout.write(
                        f"    … {total_inserted} rows inserted", ending="\r"
                    )
                    self.stdout.flush()

        # flush remainder
        if rows_buffer:
            with connection.cursor() as cur:
                cur.executemany(insert_sql, rows_buffer)
            total_inserted += len(rows_buffer)

        self.stdout.write("")  # newline after \r
        self.stdout.write(
            self.style.SUCCESS(
                f"  Inserted {total_inserted:,} metric rows "
                f"({hours}h × {total_minutes} minutes × {total_gpus} GPUs)"
            )
        )

        # ── 6. Summary ────────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Seed complete!"))
        self.stdout.write(f"  Organization : {org.name} (slug: {org.slug})")
        self.stdout.write(f"  Cluster      : {cluster.name} ({cluster.cloud})")
        self.stdout.write(f"  Nodes        : {len(nodes)}")
        self.stdout.write(f"  GPUs total   : {total_gpus}")
        self.stdout.write(f"  Metric rows  : {total_inserted:,}")
        self.stdout.write(f"  Time range   : last {hours} hours")
        self.stdout.write("")
        self.stdout.write("  Login:  demo / demo")
        self.stdout.write("  Dashboard: http://localhost:8000/")
