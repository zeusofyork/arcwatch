# monitor/views/settings_views.py (minimal stub for now)
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.http import HttpResponse


def _get_org(user):
    try:
        return user.profile.organization
    except Exception:
        return None


def _is_admin(user):
    try:
        return user.profile.role in ('admin', 'owner')
    except Exception:
        return False


@login_required
def settings_root(request):
    return redirect('/settings/api-keys/')


@login_required
def settings_api_keys(request):
    return HttpResponse('stub')


@login_required
def settings_alert_rules(request):
    return HttpResponse('stub')


@login_required
def settings_resources(request):
    return HttpResponse('stub')


@login_required
def settings_members(request):
    return HttpResponse('stub')


def accept_invite(request, token):
    return HttpResponse('stub')
