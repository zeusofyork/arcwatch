"""
monitor/management/commands/seed_demo_data.py

Management command to seed demo GPU + inference + cost + alert data.

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

from monitor.models import (
    GPU,
    GPUCluster,
    GPUNode,
    GPUPricing,
    InferenceEndpoint,
    AlertRule,
    AlertEvent,
    Organization,
)


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

# Inference endpoint demo configs
INFERENCE_ENDPOINTS = [
    {
        "name": "llama-70b-prod",
        "engine": "vllm",
        "model": "meta-llama/Llama-3.1-70B-Instruct",
        "base_rps": 18.0,
        "base_tps": 2200.0,
        "base_latency": 95.0,
        "base_kv_cache": 72.0,
        "status": "serving",
    },
    {
        "name": "mistral-7b-fast",
        "engine": "vllm",
        "model": "mistralai/Mistral-7B-Instruct-v0.3",
        "base_rps": 45.0,
        "base_tps": 5800.0,
        "base_latency": 35.0,
        "base_kv_cache": 48.0,
        "status": "serving",
    },
    {
        "name": "qwen-72b-batch",
        "engine": "tgi",
        "model": "Qwen/Qwen2.5-72B-Instruct",
        "base_rps": 8.0,
        "base_tps": 1400.0,
        "base_latency": 210.0,
        "base_kv_cache": 85.0,
        "status": "serving",
    },
    {
        "name": "deepseek-v3-exp",
        "engine": "ollama",
        "model": "deepseek-ai/DeepSeek-V3",
        "base_rps": 2.0,
        "base_tps": 380.0,
        "base_latency": 480.0,
        "base_kv_cache": 30.0,
        "status": "idle",
    },
]

# GPU pricing reference data
GPU_PRICING = [
    {"pattern": "H100", "rate": "12.2900", "provider": "CoreWeave"},
    {"pattern": "A100", "rate": "8.5000", "provider": "AWS"},
    {"pattern": "A10G", "rate": "3.5000", "provider": "AWS"},
    {"pattern": "RTX 4090", "rate": "2.2000", "provider": "Lambda Labs"},
]


def _business_hour_factor(dt):
    """
    Return a utilization multiplier based on time-of-day.
    Higher during business hours (08:00-20:00 UTC), lower at night.
    """
    hour = dt.hour + dt.minute / 60.0
    angle = math.pi * (hour - 2) / 12
    return 0.40 + 0.60 * max(0.0, math.sin(angle))


class Command(BaseCommand):
    help = "Seed demo GPU telemetry, inference endpoints, cost, and alert data."

    def add_arguments(self, parser):
        parser.add_argument("--nodes", type=int, default=4)
        parser.add_argument("--gpus-per-node", type=int, default=4)
        parser.add_argument("--hours", type=int, default=6)
        parser.add_argument("--clear", action="store_true", default=False)

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
                cur.execute(
                    "DELETE FROM gpu_metrics WHERE node_name LIKE 'demo-node-%'"
                )
                deleted_gpu = cur.rowcount
                cur.execute("DELETE FROM inference_metrics")
                deleted_inf = cur.rowcount
                cur.execute("DELETE FROM cost_snapshots")
                deleted_cost = cur.rowcount
            self.stdout.write(
                self.style.WARNING(
                    f"  Cleared {deleted_gpu} gpu_metrics, {deleted_inf} inference_metrics,"
                    f" {deleted_cost} cost_snapshots rows"
                )
            )
            GPUNode.objects_unscoped.filter(cluster=cluster).delete()
            InferenceEndpoint.objects_unscoped.filter(organization=org).delete()
            AlertRule.objects.filter(organization=org).delete()
            self.stdout.write(self.style.WARNING("  Cleared existing demo nodes/GPUs/endpoints/rules"))

        # ── 4. Build nodes + GPUs ─────────────────────────────────────────────
        gpu_type_name, vram_gb = random.choice(GPU_TYPES)
        instance_type, hourly_cost = random.choice(INSTANCE_TYPES)
        memory_total_mb = vram_gb * 1024

        nodes = []
        all_gpus = []

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
                base_util = random.uniform(20, 85)

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
                all_gpus.append((gpu.uuid, node.hostname, g, base_util, model_name))

        total_gpus = len(all_gpus)
        self.stdout.write(
            self.style.SUCCESS(
                f"  Upserted {len(nodes)} nodes × {gpus_per_node} GPUs = {total_gpus} GPU records"
            )
        )

        # ── 5. Generate GPU historical metrics ────────────────────────────────
        self.stdout.write(f"  Generating {hours}h of GPU metrics at 1-min resolution…")

        now = timezone.now().replace(second=0, microsecond=0)
        total_minutes = hours * 60
        batch_size = 10_000

        gpu_insert_sql = """
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
                util = max(0.0, min(100.0,
                    base_util * bh_factor + random.gauss(0, 5)))
                mem_used = int(memory_total_mb * util / 100 * random.uniform(0.9, 1.1))
                mem_used = max(512, min(memory_total_mb, mem_used))
                temp = int(28 + util * 0.62 + random.uniform(-2, 2))
                power = round(45 + util * 3.6 + random.gauss(0, 8), 1)
                power = max(30.0, min(400.0, power))
                sm_clock = int(900 + util * 4.5)
                mem_clock = random.choice([877, 1215, 1593])

                rows_buffer.append((
                    ts_str, gpu_uuid, node_name,
                    round(util, 2), mem_used, memory_total_mb,
                    temp, power, sm_clock, mem_clock,
                    random.randint(0, 200_000_000),
                    random.randint(0, 100_000_000),
                    0, 0,
                ))

                if len(rows_buffer) >= batch_size:
                    with connection.cursor() as cur:
                        cur.executemany(gpu_insert_sql, rows_buffer)
                    total_inserted += len(rows_buffer)
                    rows_buffer = []
                    self.stdout.write(
                        f"    … {total_inserted} rows inserted", ending="\r"
                    )
                    self.stdout.flush()

        if rows_buffer:
            with connection.cursor() as cur:
                cur.executemany(gpu_insert_sql, rows_buffer)
            total_inserted += len(rows_buffer)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"  Inserted {total_inserted:,} GPU metric rows"
            )
        )

        # ── 6. GPU Pricing entries ────────────────────────────────────────────
        self.stdout.write("  Seeding GPU pricing entries…")
        for p in GPU_PRICING:
            GPUPricing.objects.get_or_create(
                gpu_model_pattern=p["pattern"],
                pricing_type="on_demand",
                defaults={
                    "hourly_rate": p["rate"],
                    "provider": p["provider"],
                },
            )
        self.stdout.write(self.style.SUCCESS(f"  Upserted {len(GPU_PRICING)} pricing entries"))

        # ── 7. InferenceEndpoints ─────────────────────────────────────────────
        self.stdout.write("  Seeding inference endpoints…")
        endpoints_created = []
        for ep_cfg in INFERENCE_ENDPOINTS:
            ep, _ = InferenceEndpoint.objects_unscoped.get_or_create(
                organization=org,
                name=ep_cfg["name"],
                defaults={
                    "engine": ep_cfg["engine"],
                    "current_model": ep_cfg["model"],
                    "status": ep_cfg["status"],
                    "is_active": True,
                    "url": f"http://localhost:8{8000 + INFERENCE_ENDPOINTS.index(ep_cfg)}/v1",
                    "current_requests_per_sec": ep_cfg["base_rps"],
                    "current_tokens_per_sec": ep_cfg["base_tps"],
                    "current_avg_latency_ms": ep_cfg["base_latency"],
                    "current_p99_latency_ms": ep_cfg["base_latency"] * 4.5,
                    "current_queue_depth": random.randint(0, 8),
                    "current_kv_cache_usage_pct": ep_cfg["base_kv_cache"],
                    "current_batch_utilization": round(random.uniform(4, 16), 1),
                    "last_seen": now,
                },
            )
            endpoints_created.append(ep)
        self.stdout.write(
            self.style.SUCCESS(f"  Upserted {len(endpoints_created)} inference endpoints")
        )

        # ── 8. Inference metrics hypertable rows ──────────────────────────────
        self.stdout.write(f"  Generating {hours}h of inference metrics at 1-min resolution…")

        inf_insert_sql = """
            INSERT INTO inference_metrics (
                time, endpoint_id,
                model_name,
                requests_running, requests_waiting,
                prompt_throughput, generation_throughput,
                gpu_cache_usage, cpu_cache_usage,
                latency_p50, latency_p95, latency_p99,
                ttft_p50, ttft_p95, ttft_p99,
                tpot_avg, preemptions_total, batch_size_avg
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT DO NOTHING
        """

        inf_rows = []
        inf_total = 0

        for ep, ep_cfg in zip(endpoints_created, INFERENCE_ENDPOINTS):
            ep_int_id = abs(hash(str(ep.pk))) % (2 ** 31)
            for minute_offset in range(total_minutes, 0, -1):
                ts = now - timedelta(minutes=minute_offset)
                bh = _business_hour_factor(ts)
                ts_str = ts.isoformat()

                rps = max(0, ep_cfg["base_rps"] * bh + random.gauss(0, ep_cfg["base_rps"] * 0.1))
                tps = max(0, ep_cfg["base_tps"] * bh + random.gauss(0, ep_cfg["base_tps"] * 0.08))
                lat = max(5, ep_cfg["base_latency"] + random.gauss(0, ep_cfg["base_latency"] * 0.15))
                kv = max(0, min(100, ep_cfg["base_kv_cache"] + random.gauss(0, 5)))

                inf_rows.append((
                    ts_str,
                    ep_int_id,
                    ep_cfg["model"],
                    int(rps * 2),           # requests_running
                    max(0, int(rps * 0.3)), # requests_waiting
                    tps * 0.25,             # prompt_throughput
                    tps,                    # generation_throughput
                    kv / 100.0,             # gpu_cache_usage (0-1)
                    random.uniform(0.01, 0.1),  # cpu_cache_usage
                    round(lat, 1),          # latency_p50
                    round(lat * 2.5, 1),    # latency_p95
                    round(lat * 5.0, 1),    # latency_p99
                    round(lat * 0.3, 1),    # ttft_p50
                    round(lat * 0.8, 1),    # ttft_p95
                    round(lat * 1.5, 1),    # ttft_p99
                    round(random.uniform(3, 8), 2),  # tpot_avg
                    0,                       # preemptions_total
                    round(random.uniform(4, 16), 1), # batch_size_avg
                ))

                if len(inf_rows) >= batch_size:
                    with connection.cursor() as cur:
                        cur.executemany(inf_insert_sql, inf_rows)
                    inf_total += len(inf_rows)
                    inf_rows = []
                    self.stdout.write(
                        f"    … {inf_total} inference rows inserted", ending="\r"
                    )
                    self.stdout.flush()

        if inf_rows:
            with connection.cursor() as cur:
                cur.executemany(inf_insert_sql, inf_rows)
            inf_total += len(inf_rows)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"  Inserted {inf_total:,} inference metric rows"
            )
        )

        # ── 9. Cost snapshots ─────────────────────────────────────────────────
        self.stdout.write(f"  Generating {hours}h of cost snapshots at 1-min resolution…")

        from monitor.models import GPUPricing as _GPUPricing

        pricing_entries = list(_GPUPricing.objects.all())

        def _match_rate(model_str):
            model_lower = (model_str or "").lower()
            for p in pricing_entries:
                if p.gpu_model_pattern.lower() in model_lower:
                    return float(p.hourly_rate)
            return 8.50  # default fallback

        cost_insert_sql = """
            INSERT INTO cost_snapshots (
                time, gpu_uuid, endpoint_id,
                model_name, hourly_rate,
                utilization, cost_this_period, waste_this_period
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """

        cost_rows = []
        cost_total = 0
        interval_secs = 60.0

        for minute_offset in range(total_minutes, 0, -1):
            ts = now - timedelta(minutes=minute_offset)
            bh = _business_hour_factor(ts)
            ts_str = ts.isoformat()

            for gpu_uuid, node_name, gpu_index, base_util, model_name in all_gpus:
                util = max(0.0, min(100.0,
                    base_util * bh + random.gauss(0, 5)))
                rate = _match_rate(gpu_type_name)
                cost = rate * (interval_secs / 3600.0)
                waste = cost * (1.0 - util / 100.0)

                cost_rows.append((
                    ts_str,
                    gpu_uuid,
                    None,
                    model_name,
                    rate,
                    round(util, 2),
                    round(cost, 8),
                    round(waste, 8),
                ))

                if len(cost_rows) >= batch_size:
                    with connection.cursor() as cur:
                        cur.executemany(cost_insert_sql, cost_rows)
                    cost_total += len(cost_rows)
                    cost_rows = []
                    self.stdout.write(
                        f"    … {cost_total} cost rows inserted", ending="\r"
                    )
                    self.stdout.flush()

        if cost_rows:
            with connection.cursor() as cur:
                cur.executemany(cost_insert_sql, cost_rows)
            cost_total += len(cost_rows)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"  Inserted {cost_total:,} cost snapshot rows")
        )

        # ── 10. Alert rules + events ──────────────────────────────────────────
        self.stdout.write("  Seeding alert rules…")

        rule1, _ = AlertRule.objects.get_or_create(
            organization=org,
            name="GPU Underutilization Alert",
            defaults={
                "metric": "gpu_utilization_low",
                "threshold_value": 20.0,
                "duration_seconds": 600,
                "is_enabled": True,
            },
        )
        rule2, _ = AlertRule.objects.get_or_create(
            organization=org,
            name="High Inference Latency",
            defaults={
                "metric": "latency_high",
                "threshold_value": 500.0,
                "duration_seconds": 300,
                "is_enabled": True,
            },
        )
        rule3, _ = AlertRule.objects.get_or_create(
            organization=org,
            name="GPU Memory Pressure",
            defaults={
                "metric": "gpu_memory_high",
                "threshold_value": 90.0,
                "duration_seconds": 180,
                "is_enabled": True,
            },
        )
        self.stdout.write(self.style.SUCCESS("  Upserted 3 alert rules"))

        # Seed a few sample AlertEvents
        if not AlertEvent.objects.filter(rule__organization=org).exists():
            AlertEvent.objects.create(
                rule=rule1,
                severity="warning",
                message=f"GPU util fell below 20% on demo-node-02 for 10+ minutes",
                context={"node": "demo-node-02", "utilization": 14.2},
                notification_sent=False,
            )
            AlertEvent.objects.create(
                rule=rule2,
                severity="warning",
                message="qwen-72b-batch p99 latency exceeded 500ms threshold",
                context={"endpoint": "qwen-72b-batch", "latency_p99": 720.0},
                notification_sent=True,
                resolved_at=now - timedelta(hours=1),
            )
            AlertEvent.objects.create(
                rule=rule3,
                severity="critical",
                message="GPU memory usage reached 93% on demo-node-00:GPU0",
                context={"node": "demo-node-00", "gpu_index": 0, "memory_pct": 93.1},
                notification_sent=True,
                resolved_at=now - timedelta(minutes=30),
            )
            self.stdout.write(self.style.SUCCESS("  Created 3 sample alert events"))

        # ── 11. Summary ───────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Seed complete!"))
        self.stdout.write(f"  Organization   : {org.name} (slug: {org.slug})")
        self.stdout.write(f"  Cluster        : {cluster.name} ({cluster.cloud})")
        self.stdout.write(f"  Nodes          : {len(nodes)}")
        self.stdout.write(f"  GPUs total     : {total_gpus}")
        self.stdout.write(f"  GPU metrics    : {total_inserted:,} rows")
        self.stdout.write(f"  Inf endpoints  : {len(endpoints_created)}")
        self.stdout.write(f"  Inf metrics    : {inf_total:,} rows")
        self.stdout.write(f"  Cost snapshots : {cost_total:,} rows")
        self.stdout.write(f"  Alert rules    : 3")
        self.stdout.write(f"  Time range     : last {hours} hours")
        self.stdout.write("")
        self.stdout.write("  Login:     demo / demo")
        self.stdout.write("  Dashboard: http://localhost:8000/")
