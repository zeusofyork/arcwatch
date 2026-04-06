"""
monitor/views/settings_views.py -- Settings management views (API Keys, Alert Rules, Resources, Members).
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from monitor.decorators import is_htmx, require_admin
from monitor.forms import APIKeyCreateForm, AlertRuleForm, InviteForm
from monitor.models import APIKey, AlertRule, Invite


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
    is_admin = _is_admin(request.user)
    new_raw_key = None

    if request.method == 'POST':
        if not is_admin:
            return HttpResponseForbidden("Admin access required.")
        form = APIKeyCreateForm(request.POST)
        if form.is_valid():
            _, new_raw_key = APIKey.create_key(
                organization=org,
                user=request.user,
                name=form.cleaned_data['name'],
                scopes=form.cleaned_data['scopes'],
            )
    else:
        form = APIKeyCreateForm()

    return render(request, 'monitor/settings_api_keys.html', {
        'active_tab': 'api-keys',
        'org': org,
        'is_admin': is_admin,
        'api_keys': org.api_keys.all() if org else [],
        'form': form,
        'new_raw_key': new_raw_key,
    })


@login_required
@require_admin
def revoke_api_key(request, key_id):
    org = _get_org(request.user)
    api_key = get_object_or_404(APIKey, pk=key_id, organization=org)
    if request.method == 'POST':
        api_key.active = False
        api_key.save(update_fields=['active'])
    if is_htmx(request):
        return render(request, 'monitor/fragments/api_key_row.html', {
            'key': api_key, 'is_admin': True,
        })
    return redirect('/settings/api-keys/')


# ── Alert Rules ───────────────────────────────────────────────────────────────

@login_required
def settings_alert_rules(request):
    org = _get_org(request.user)
    return render(request, 'monitor/settings_alert_rules.html', {
        'active_tab': 'alert-rules',
        'org': org,
        'is_admin': _is_admin(request.user),
        'rules': org.alert_rules.all() if org else [],
        'form': AlertRuleForm(),
    })


@login_required
@require_admin
def create_alert_rule(request):
    if request.method != 'POST':
        return redirect('/settings/alert-rules/')
    org = _get_org(request.user)
    if org is None:
        return HttpResponseForbidden("No organization.")
    form = AlertRuleForm(request.POST)
    if form.is_valid():
        rule = form.save(commit=False)
        rule.organization = org
        rule.save()
        return redirect('/settings/alert-rules/')
    # Re-render page with form errors
    return render(request, 'monitor/settings_alert_rules.html', {
        'active_tab': 'alert-rules',
        'org': org,
        'is_admin': True,
        'rules': org.alert_rules.all(),
        'form': form,
        'show_form': True,
    })


@login_required
@require_admin
def toggle_alert_rule(request, rule_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    org = _get_org(request.user)
    rule = get_object_or_404(AlertRule, pk=rule_id, organization=org)
    rule.is_enabled = not rule.is_enabled
    rule.save(update_fields=['is_enabled'])
    return render(request, 'monitor/fragments/alert_rule_toggle.html', {
        'rule': rule, 'is_admin': _is_admin(request.user),
    })


@login_required
@require_admin
def delete_alert_rule(request, rule_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    org = _get_org(request.user)
    rule = get_object_or_404(AlertRule, pk=rule_id, organization=org)
    rule.delete()
    return HttpResponse('')


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
