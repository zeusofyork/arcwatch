from django.urls import path

from monitor.rest_api import ingest_gpu, ingest_inference
from monitor.views.dashboard_views import gpu_fleet_dashboard
from monitor.views.inference_views import inference_dashboard
from monitor.views.cost_views import cost_dashboard
from monitor.views.alert_views import alerts_dashboard

app_name = 'monitor'

urlpatterns = [
    # ── Dashboard views ───────────────────────────────────────────────────────
    path('', gpu_fleet_dashboard, name='gpu_fleet_dashboard'),
    path('inference/', inference_dashboard, name='inference_dashboard'),
    path('costs/', cost_dashboard, name='cost_dashboard'),
    path('alerts/', alerts_dashboard, name='alerts_dashboard'),

    # ── REST API ──────────────────────────────────────────────────────────────
    path('api/v1/ingest/gpu/', ingest_gpu, name='api_ingest_gpu'),
    path('api/v1/ingest/inference/', ingest_inference, name='api_ingest_inference'),
]
