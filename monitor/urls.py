from django.urls import path

from monitor.rest_api import gpu_fleet_dashboard, ingest_gpu

app_name = 'monitor'

urlpatterns = [
    path('', gpu_fleet_dashboard, name='gpu_fleet_dashboard'),
    path('api/v1/ingest/gpu/', ingest_gpu, name='api_ingest_gpu'),
]
