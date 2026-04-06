"""
monitor/views/settings_views.py -- Settings management views (API Keys, Alert Rules, Resources, Members).
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from monitor.decorators import require_admin


# ── Shared helpers ────────────────────────────────────────────────────────────

def _get_org(user):
    """Return the organization for the logged-in user, or None."""
    try:
        return user.profile.organization
    except Exception:
        return None


def _is_admin(user):
    """Return True if the user has admin or owner role."""
    try:
        return user.profile.role in ('admin', 'owner')
    except Exception:
        return False


# ── Settings root ─────────────────────────────────────────────────────────────

@login_required
def settings_root(request):
    return redirect('/settings/api-keys/')


# ── API Keys ──────────────────────────────────────────────────────────────────

@login_required
def settings_api_keys(request):
    org = _get_org(request.user)
    return render(request, 'monitor/settings_api_keys.html', {
        'active_tab': 'api-keys',
        'org': org,
        'is_admin': _is_admin(request.user),
        'api_keys': org.api_keys.all() if org else [],
    })


# ── Alert Rules ───────────────────────────────────────────────────────────────

@login_required
def settings_alert_rules(request):
    org = _get_org(request.user)
    from monitor.forms import AlertRuleForm
    return render(request, 'monitor/settings_alert_rules.html', {
        'active_tab': 'alert-rules',
        'org': org,
        'is_admin': _is_admin(request.user),
        'rules': org.alert_rules.all() if org else [],
        'form': AlertRuleForm(),
    })


# ── Resources ─────────────────────────────────────────────────────────────────

@login_required
def settings_resources(request):
    org = _get_org(request.user)
    tab = request.GET.get('tab', 'clusters')
    clusters = org.gpu_clusters.filter(is_active=True).prefetch_related('nodes') if org else []
    endpoints = org.inference_endpoints.filter(is_active=True) if org else []
    return render(request, 'monitor/settings_resources.html', {
        'active_tab': 'resources',
        'tab': tab,
        'org': org,
        'is_admin': _is_admin(request.user),
        'clusters': clusters,
        'endpoints': endpoints,
    })


# ── Members ───────────────────────────────────────────────────────────────────

@login_required
def settings_members(request):
    org = _get_org(request.user)
    from monitor.models import Invite
    from monitor.forms import InviteForm
    members = org.get_members().select_related('profile') if org else []
    pending = Invite.objects.filter(organization=org, accepted_at__isnull=True) if org else []
    return render(request, 'monitor/settings_members.html', {
        'active_tab': 'members',
        'org': org,
        'is_admin': _is_admin(request.user),
        'members': members,
        'pending_invites': pending,
        'form': InviteForm(),
    })


# ── Accept invite (no login required — used by new users) ────────────────────

def accept_invite(request, token):
    return render(request, 'monitor/accept_invite.html', {})
