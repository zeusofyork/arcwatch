"""
monitor/models/base.py -- Tenant-aware manager and thread-local org scoping helpers.
"""
from django.db import models


# ── Thread-local storage ──────────────────────────────────────────────────────

_thread_local = None


def _get_thread_local():
    global _thread_local
    if _thread_local is None:
        import threading
        _thread_local = threading.local()
    return _thread_local


# ── Tenant-Aware Manager ──────────────────────────────────────────────────────

class TenantManager(models.Manager):
    """
    Drop-in manager that auto-filters by the current org when
    set_current_org(org) has been called in the request context.

    Usage in views/middleware:
        from monitor.models import set_current_org
        set_current_org(request.user.profile.organization)

    Views that need cross-org access (admin ops) should use
    Model.objects_unscoped instead.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        tl = _get_thread_local()
        org = getattr(tl, 'current_org', None)
        if org is not None and hasattr(self.model, 'organization'):
            qs = qs.filter(organization=org)
        return qs


def set_current_org(org):
    """Call at the start of a request to scope all subsequent ORM queries."""
    _get_thread_local().current_org = org


def clear_current_org():
    """Call at the end of a request to clear tenant scoping."""
    tl = _get_thread_local()
    if hasattr(tl, 'current_org'):
        del tl.current_org
