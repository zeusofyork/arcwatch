"""
monitor/views/settings_views.py -- Settings management views (API Keys, Alert Rules, Resources, Members).
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from monitor.decorators import is_htmx, require_admin
from monitor.forms import APIKeyCreateForm, AlertRuleForm, InviteForm, GPUClusterForm, InferenceEndpointForm
from monitor.models import APIKey, AlertRule, Invite, GPUCluster, GPUNode, InferenceEndpoint


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


@login_required
@require_admin
def create_cluster(request):
    if request.method != 'POST':
        return redirect('/settings/resources/')
    org = _get_org(request.user)
    if org is None:
        return HttpResponseForbidden("No organization.")
    form = GPUClusterForm(request.POST)
    if form.is_valid():
        GPUCluster.objects_unscoped.create(organization=org, name=form.cleaned_data['name'])
    return redirect('/settings/resources/')


@login_required
@require_admin
def deactivate_cluster(request, cluster_id):
    org = _get_org(request.user)
    cluster = get_object_or_404(GPUCluster, pk=cluster_id, organization=org)
    if request.method == 'POST':
        cluster.is_active = False
        cluster.save(update_fields=['is_active'])
    return HttpResponse('<span style="background:rgba(100,116,139,.1);border:1px solid #475569;color:#64748b;font-size:.62rem;padding:2px 7px;border-radius:10px">inactive</span>')


@login_required
@require_admin
def delete_cluster(request, cluster_id):
    org = _get_org(request.user)
    cluster = get_object_or_404(GPUCluster, pk=cluster_id, organization=org)
    if request.method == 'POST':
        cluster.delete()
    return HttpResponse('')


@login_required
@require_admin
def deactivate_node(request, node_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    org = _get_org(request.user)
    node = get_object_or_404(GPUNode, pk=node_id, organization=org)
    node.is_active = False
    node.save(update_fields=['is_active'])
    return HttpResponse('<span style="background:rgba(100,116,139,.1);border:1px solid #475569;color:#64748b;font-size:.62rem;padding:2px 7px;border-radius:10px">inactive</span>')


@login_required
@require_admin
def delete_node(request, node_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    org = _get_org(request.user)
    node = get_object_or_404(GPUNode, pk=node_id, organization=org)
    node.delete()
    return HttpResponse('')


@login_required
@require_admin
def create_endpoint(request):
    if request.method != 'POST':
        return redirect('/settings/resources/?tab=endpoints')
    org = _get_org(request.user)
    form = InferenceEndpointForm(request.POST)
    if form.is_valid():
        InferenceEndpoint.objects.create(
            organization=org,
            name=form.cleaned_data['name'],
            engine=form.cleaned_data['engine'],
            url=form.cleaned_data.get('url', ''),
        )
    return redirect('/settings/resources/?tab=endpoints')


@login_required
@require_admin
def deactivate_endpoint(request, endpoint_id):
    org = _get_org(request.user)
    ep = get_object_or_404(InferenceEndpoint, pk=endpoint_id, organization=org)
    if request.method == 'POST':
        ep.is_active = False
        ep.save(update_fields=['is_active'])
    return HttpResponse('<span style="background:rgba(100,116,139,.1);border:1px solid #475569;color:#64748b;font-size:.62rem;padding:2px 7px;border-radius:10px">retired</span>')


@login_required
@require_admin
def delete_endpoint(request, endpoint_id):
    org = _get_org(request.user)
    ep = get_object_or_404(InferenceEndpoint, pk=endpoint_id, organization=org)
    if request.method == 'POST':
        ep.delete()
    return HttpResponse('')


# ── Members ───────────────────────────────────────────────────────────────────

@login_required
def settings_members(request):
    org = _get_org(request.user)
    members = org.get_members().select_related('profile') if org else []
    pending = Invite.objects.filter(organization=org, accepted_at__isnull=True) if org else []
    return render(request, 'monitor/settings_members.html', {
        'active_tab': 'members', 'org': org, 'is_admin': _is_admin(request.user),
        'members': members, 'pending_invites': pending, 'form': InviteForm(),
    })


@login_required
@require_admin
def change_member_role(request, user_id):
    from django.contrib.auth.models import User as DjangoUser
    org = _get_org(request.user)
    member = get_object_or_404(DjangoUser, pk=user_id, profile__organization=org)
    if request.method == 'POST':
        role = request.POST.get('role', '')
        if role in ('viewer', 'operator', 'admin', 'owner'):
            member.profile.role = role
            member.profile.save(update_fields=['role'])
    role_colors = {
        'owner': '#76B900', 'admin': '#fbbf24',
        'operator': '#a78bfa', 'viewer': '#60a5fa',
    }
    color = role_colors.get(member.profile.role, '#94a3b8')
    return HttpResponse(
        f'<span style="background:rgba(0,0,0,.1);border:1px solid {color}40;color:{color};'
        f'font-size:.62rem;padding:2px 7px;border-radius:10px;cursor:pointer">'
        f'{member.profile.role} &#9662;</span>'
    )


@login_required
@require_admin
def remove_member(request, user_id):
    from django.contrib.auth.models import User as DjangoUser
    org = _get_org(request.user)
    member = get_object_or_404(DjangoUser, pk=user_id, profile__organization=org)
    if request.method == 'POST' and member != request.user:
        member.profile.organization = None
        member.profile.save(update_fields=['organization'])
    return HttpResponse('')


@login_required
@require_admin
def invite_member(request):
    if request.method != 'POST':
        return redirect('/settings/members/')
    org = _get_org(request.user)
    if org is None:
        return HttpResponseForbidden("No organization.")
    from django.core.mail import send_mail
    from django.conf import settings as django_settings
    form = InviteForm(request.POST)
    if form.is_valid():
        invite = Invite.objects.create(
            organization=org,
            invited_by=request.user,
            email=form.cleaned_data['email'],
            role=form.cleaned_data['role'],
        )
        accept_url = request.build_absolute_uri(f'/accounts/accept-invite/{invite.token}/')
        send_mail(
            subject=f"You're invited to {org.name} on ArcWatch",
            message=(
                f"Hi,\n\n"
                f"{request.user.username} has invited you to join {org.name} on ArcWatch "
                f"as a {invite.role}.\n\n"
                f"Accept your invite here (expires in 7 days):\n{accept_url}\n\n"
                f"— The ArcWatch Team"
            ),
            from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@arcwatch.local'),
            recipient_list=[invite.email],
            fail_silently=True,
        )
    return redirect('/settings/members/')


@login_required
@require_admin
def revoke_invite(request, token):
    org = _get_org(request.user)
    invite = get_object_or_404(Invite, token=token, organization=org, accepted_at__isnull=True)
    if request.method == 'POST':
        invite.delete()
    return HttpResponse('')


@login_required
@require_admin
def resend_invite(request, token):
    from django.core.mail import send_mail
    from django.conf import settings as django_settings
    org = _get_org(request.user)
    invite = get_object_or_404(Invite, token=token, organization=org, accepted_at__isnull=True)
    if request.method == 'POST':
        accept_url = request.build_absolute_uri(f'/accounts/accept-invite/{invite.token}/')
        send_mail(
            subject=f"You're invited to {org.name} on ArcWatch (reminder)",
            message=f"Accept your invite here (expires in 7 days):\n{accept_url}",
            from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@arcwatch.local'),
            recipient_list=[invite.email],
            fail_silently=True,
        )
    return HttpResponse('<span style="color:#60a5fa;font-size:.68rem">Sent &#10003;</span>')


# ── Accept invite (no login required — used by new users) ────────────────────

def accept_invite(request, token):
    from django.contrib.auth import login
    from django.contrib.auth.models import User as DjangoUser
    from django.utils import timezone as tz
    from monitor.forms import AcceptInviteForm

    invite = get_object_or_404(Invite, token=token)

    if invite.is_accepted:
        return redirect('/accounts/login/')

    if invite.is_expired:
        return render(request, 'monitor/accept_invite.html', {
            'error': "This invite has expired. Ask an admin to resend it.",
            'invite': invite,
        })

    if request.method == 'POST':
        form = AcceptInviteForm(request.POST)
        if form.is_valid():
            user = DjangoUser.objects.create_user(
                username=form.cleaned_data['username'],
                email=invite.email,
                password=form.cleaned_data['password'],
            )
            user.profile.organization = invite.organization
            user.profile.role = invite.role
            user.profile.save()
            invite.accepted_at = tz.now()
            invite.save(update_fields=['accepted_at'])
            login(request, user)
            return redirect('/')
    else:
        form = AcceptInviteForm()

    return render(request, 'monitor/accept_invite.html', {
        'form': form,
        'invite': invite,
    })
