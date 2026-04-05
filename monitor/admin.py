"""
monitor/admin.py -- Django admin registrations for GPUWatch models.
"""
from django.contrib import admin

from .models import (
    Organization, APIKey, Team, UserProfile,
    GPUCluster, GPUNode, GPU,
    InferenceEndpoint, GPUPricing, AlertRule, AlertEvent,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'owner', 'plan', 'created_at')
    list_filter = ('plan',)
    search_fields = ('name', 'slug', 'owner__username')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'slug', 'cost_center')
    list_filter = ('organization',)
    search_fields = ('name', 'slug', 'cost_center')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'team', 'role')
    list_filter = ('role', 'organization')
    search_fields = ('user__username', 'user__email')


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'user', 'key_prefix', 'active', 'created_at', 'last_used_at')
    list_filter = ('active', 'organization')
    search_fields = ('name', 'key_prefix', 'user__username')
    readonly_fields = ('key_hash', 'key_prefix', 'created_at', 'last_used_at')


@admin.register(GPUCluster)
class GPUClusterAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'cloud', 'region', 'created_at')
    list_filter = ('cloud', 'organization')
    search_fields = ('name', 'region')


@admin.register(GPUNode)
class GPUNodeAdmin(admin.ModelAdmin):
    list_display = ('hostname', 'organization', 'cluster', 'gpu_count', 'gpu_type', 'status', 'last_seen')
    list_filter = ('status', 'organization', 'cluster')
    search_fields = ('hostname', 'gpu_type', 'instance_type')


@admin.register(GPU)
class GPUAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'organization', 'node', 'status', 'current_utilization', 'last_updated')
    list_filter = ('status', 'organization')
    search_fields = ('uuid', 'current_model_name', 'node__hostname')
    readonly_fields = ('uuid',)


@admin.register(InferenceEndpoint)
class InferenceEndpointAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'engine', 'status', 'current_model', 'last_seen')
    list_filter = ('engine', 'status', 'organization')
    search_fields = ('name', 'current_model', 'url')
    readonly_fields = ('id', 'created_at')


@admin.register(GPUPricing)
class GPUPricingAdmin(admin.ModelAdmin):
    list_display = ('gpu_model_pattern', 'hourly_rate', 'provider', 'pricing_type', 'created_at')
    list_filter = ('pricing_type', 'provider')
    search_fields = ('gpu_model_pattern', 'provider')


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'metric', 'threshold_value', 'duration_seconds', 'is_enabled')
    list_filter = ('metric', 'is_enabled', 'organization')
    search_fields = ('name',)


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'rule', 'severity', 'triggered_at', 'resolved_at', 'notification_sent')
    list_filter = ('severity', 'notification_sent', 'rule__organization')
    search_fields = ('message',)
    readonly_fields = ('triggered_at',)
