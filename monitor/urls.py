from django.urls import path

from monitor.rest_api import ingest_gpu, ingest_inference
from monitor.views.dashboard_views import gpu_fleet_dashboard
from monitor.views.inference_views import inference_dashboard
from monitor.views.cost_views import cost_dashboard
from monitor.views.alert_views import alerts_dashboard
from monitor.views.settings_views import (
    settings_root, settings_api_keys, settings_alert_rules,
    settings_resources, settings_members,
)

app_name = 'monitor'

urlpatterns = [
    # ── Dashboard views ───────────────────────────────────────────────────────
    path('', gpu_fleet_dashboard, name='gpu_fleet_dashboard'),
    path('inference/', inference_dashboard, name='inference_dashboard'),
    path('costs/', cost_dashboard, name='cost_dashboard'),
    path('alerts/', alerts_dashboard, name='alerts_dashboard'),

    # ── Settings views ────────────────────────────────────────────────────────
    path('settings/', settings_root, name='settings_root'),
    path('settings/api-keys/', settings_api_keys, name='settings_api_keys'),
    path('settings/alert-rules/', settings_alert_rules, name='settings_alert_rules'),
    path('settings/resources/', settings_resources, name='settings_resources'),
    path('settings/members/', settings_members, name='settings_members'),

    # ── REST API ──────────────────────────────────────────────────────────────
    path('api/v1/ingest/gpu/', ingest_gpu, name='api_ingest_gpu'),
    path('api/v1/ingest/inference/', ingest_inference, name='api_ingest_inference'),
]
