# Settings Management UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/settings/` section to ArcWatch with API Keys, Alert Rules, Resources, and Members pages, all protected by Django login with role-based write access.

**Architecture:** Django FBVs behind `@login_required` and a custom `require_admin` decorator; HTMX for inline mutations (toggle, revoke, deactivate, remove) returning HTML fragments; a UUID-token email invite flow for new members. All settings templates extend `settings_base.html` which extends `base.html`.

**Tech Stack:** Django 4.2, HTMX 1.9.12 (CDN), Django signals (UserProfile auto-create already exists), `django.core.mail.send_mail`, SQLite in tests (`USE_SQLITE=1`), pytest-django with `--keepdb`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `arcwatch/settings.py` | LOGIN_URL, LOGIN_REDIRECT_URL, EMAIL_BACKEND |
| Modify | `arcwatch/urls.py` | wire auth + settings URLs |
| Modify | `monitor/urls.py` | include settings URLs |
| Create | `monitor/decorators.py` | `require_admin`, `is_htmx` |
| Create | `monitor/forms.py` | all settings forms |
| Modify | `monitor/models/organization.py` | add `Invite` model |
| Modify | `monitor/models/__init__.py` | export `Invite` |
| Modify | `monitor/models/gpu.py` | add `is_active` to GPUCluster, GPUNode |
| Create | `monitor/migrations/0007_invite_and_is_active.py` | single migration |
| Create | `monitor/views/settings_views.py` | all settings views |
| Modify | `monitor/views/dashboard_views.py` | add `@login_required` |
| Modify | `monitor/views/inference_views.py` | add `@login_required` |
| Modify | `monitor/views/cost_views.py` | add `@login_required` |
| Modify | `monitor/views/alert_views.py` | add `@login_required` |
| Modify | `monitor/templates/monitor/base.html` | HTMX CDN, Settings nav, user/logout |
| Create | `monitor/templates/monitor/login.html` | login form |
| Create | `monitor/templates/monitor/settings_base.html` | settings two-column layout |
| Create | `monitor/templates/monitor/settings_api_keys.html` | API keys list + create |
| Create | `monitor/templates/monitor/settings_alert_rules.html` | alert rules CRUD |
| Create | `monitor/templates/monitor/settings_resources.html` | clusters/nodes/endpoints |
| Create | `monitor/templates/monitor/settings_members.html` | members + invite |
| Create | `monitor/templates/monitor/accept_invite.html` | accept-invite form |
| Create | `monitor/tests/test_settings_views.py` | all settings view tests |

---

### Task 1: Auth Settings + Login Template

**Files:**
- Modify: `arcwatch/settings.py`
- Modify: `arcwatch/urls.py`
- Create: `monitor/templates/monitor/login.html`

- [ ] **Step 1: Write the failing test**

```python
# monitor/tests/test_settings_views.py
from django.test import TestCase
from django.urls import reverse


class AuthRedirectTest(TestCase):
    def test_dashboard_redirects_to_login_when_unauthenticated(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_settings_redirects_to_login_when_unauthenticated(self):
        response = self.client.get('/settings/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_login_page_renders(self):
        response = self.client.get('/accounts/login/')
        self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::AuthRedirectTest -v --keepdb
```

Expected: FAIL — login page returns 404, dashboard not protected yet.

- [ ] **Step 3: Add auth settings to `arcwatch/settings.py`**

Add after the existing `STATIC_URL` line:

```python
# Authentication
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Email (console backend for development; override in production via env vars)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'noreply@arcwatch.local'
```

- [ ] **Step 4: Wire auth URLs in `arcwatch/urls.py`**

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/', include('monitor.urls_accounts')),  # accept-invite
    path('', include('monitor.urls')),
]
```

- [ ] **Step 5: Create `monitor/urls_accounts.py`** (separate file keeps accounts URLs clean)

```python
from django.urls import path
from monitor.views.settings_views import accept_invite

urlpatterns = [
    path('accept-invite/<uuid:token>/', accept_invite, name='accept_invite'),
]
```

- [ ] **Step 6: Create `monitor/templates/monitor/login.html`**

```html
{% extends "monitor/base.html" %}
{% block content %}
<div style="display:flex;align-items:center;justify-content:center;min-height:60vh">
  <div style="width:320px">
    <h2 style="font-family:monospace;color:#e2e8f0;margin-bottom:20px">Sign in to ArcWatch</h2>
    {% if form.errors %}
    <div style="background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.3);color:#f87171;padding:10px 14px;border-radius:6px;font-size:.8rem;margin-bottom:16px">
      Invalid username or password.
    </div>
    {% endif %}
    <form method="post">
      {% csrf_token %}
      <div style="margin-bottom:12px">
        <label style="display:block;font-size:.72rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Username</label>
        <input name="username" type="text" autofocus
               style="width:100%;background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:8px 12px;border-radius:4px;font-size:.85rem;box-sizing:border-box">
      </div>
      <div style="margin-bottom:20px">
        <label style="display:block;font-size:.72rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Password</label>
        <input name="password" type="password"
               style="width:100%;background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:8px 12px;border-radius:4px;font-size:.85rem;box-sizing:border-box">
      </div>
      <input type="hidden" name="next" value="{{ next }}">
      <button type="submit"
              style="width:100%;background:#76B900;color:#000;font-weight:700;font-family:monospace;font-size:.85rem;padding:10px;border:none;border-radius:4px;cursor:pointer">
        Sign In
      </button>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Protect dashboard views — add `@login_required` to all four view files**

In `monitor/views/dashboard_views.py`, `inference_views.py`, `cost_views.py`, `alert_views.py`:

```python
from django.contrib.auth.decorators import login_required

# Add @login_required decorator above each view function, e.g.:
@login_required
def gpu_fleet_dashboard(request):
    ...
```

- [ ] **Step 8: Run tests and verify they pass**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::AuthRedirectTest -v --keepdb
```

Expected: PASS (3 tests)

- [ ] **Step 9: Commit**

```bash
git add arcwatch/settings.py arcwatch/urls.py monitor/urls_accounts.py \
        monitor/templates/monitor/login.html \
        monitor/views/dashboard_views.py monitor/views/inference_views.py \
        monitor/views/cost_views.py monitor/views/alert_views.py
git commit -m "feat: auth foundation — login_required on all views, login template, auth URLs"
```

---

### Task 2: Models — Invite + is_active + Migration

**Files:**
- Modify: `monitor/models/organization.py`
- Modify: `monitor/models/__init__.py`
- Modify: `monitor/models/gpu.py`
- Create: `monitor/migrations/0007_invite_and_is_active.py`

- [ ] **Step 1: Write the failing test**

```python
# Add to monitor/tests/test_settings_views.py

from django.contrib.auth.models import User
from monitor.models import Organization, Invite, GPUCluster, GPUNode
from django.utils import timezone
import uuid


def _make_user_and_org(username='admin', role='owner'):
    user = User.objects.create_user(username=username, password='pw')
    org = Organization.objects.create(name='TestOrg', slug='testorg', owner=user)
    user.profile.organization = org
    user.profile.role = role
    user.profile.save()
    return user, org


class InviteModelTest(TestCase):
    def test_invite_created_with_expiry(self):
        user, org = _make_user_and_org('inviteadmin')
        invite = Invite.objects.create(
            organization=org,
            invited_by=user,
            email='new@example.com',
            role='viewer',
        )
        self.assertIsNotNone(invite.token)
        self.assertFalse(invite.is_expired)
        self.assertFalse(invite.is_accepted)

    def test_is_active_on_cluster_and_node(self):
        user, org = _make_user_and_org('clusteradmin')
        cluster = GPUCluster.objects_unscoped.create(organization=org, name='test-cluster')
        self.assertTrue(cluster.is_active)
        node = GPUNode.objects_unscoped.create(
            organization=org, cluster=cluster,
            hostname='node-1', gpu_count=1, gpu_type='H100',
        )
        self.assertTrue(node.is_active)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::InviteModelTest -v --keepdb
```

Expected: FAIL — `Invite` not importable, `GPUCluster` has no `is_active`.

- [ ] **Step 3: Add `Invite` model to `monitor/models/organization.py`**

Append at the end of the file (after the `APIKey` class):

```python
import datetime


# ── Invite ─────────────────────────────────────────────────────────────────

class Invite(models.Model):
    """
    Email-based invitation for a new member to join an organization.
    Token is a UUID used as the one-time accept link.
    """
    ROLE_CHOICES = [
        ('viewer', 'Viewer'),
        ('admin', 'Admin'),
        ('owner', 'Owner'),
    ]

    token = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='invites',
    )
    invited_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_invites',
    )
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='viewer')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'accepted_at']),
            models.Index(fields=['email']),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + datetime.timedelta(days=7)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Invite({self.email} → {self.organization.slug})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_accepted(self):
        return self.accepted_at is not None

    @property
    def is_pending(self):
        return not self.is_accepted and not self.is_expired
```

Make sure `import datetime` is at the top (alongside `import uuid` already present).

- [ ] **Step 4: Add `is_active` to `GPUCluster` and `GPUNode` in `monitor/models/gpu.py`**

In the `GPUCluster` class, add after `created_at`:

```python
    is_active = models.BooleanField(default=True, db_index=True)
```

In the `GPUNode` class, add after the `status` field (or before `class Meta`):

```python
    is_active = models.BooleanField(default=True, db_index=True)
```

- [ ] **Step 5: Export `Invite` from `monitor/models/__init__.py`**

Add `Invite` to the imports. The file currently ends with something like:
```python
from .organization import Organization, Team, UserProfile, APIKey
```

Change to:
```python
from .organization import Organization, Team, UserProfile, APIKey, Invite
```

- [ ] **Step 6: Generate the migration**

```bash
cd /home/zeus/Desktop/dev/github/gpuwatch
USE_SQLITE=1 python manage.py makemigrations monitor --name invite_and_is_active
```

This creates `monitor/migrations/0007_invite_and_is_active.py`. Verify it contains `CreateModel` for `Invite` and `AddField` for `is_active` on both `GPUCluster` and `GPUNode`.

- [ ] **Step 7: Run tests and verify they pass**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::InviteModelTest -v --keepdb
```

Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add monitor/models/organization.py monitor/models/gpu.py monitor/models/__init__.py \
        monitor/migrations/0007_invite_and_is_active.py
git commit -m "feat: add Invite model and is_active fields to GPUCluster/GPUNode"
```

---

### Task 3: Decorators + Forms

**Files:**
- Create: `monitor/decorators.py`
- Create: `monitor/forms.py`

- [ ] **Step 1: Write the failing test**

```python
# Add to monitor/tests/test_settings_views.py

class DecoratorTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('dec_admin', role='owner')
        self.viewer = User.objects.create_user(username='dec_viewer', password='pw')
        self.viewer.profile.organization = self.org
        self.viewer.profile.role = 'viewer'
        self.viewer.profile.save()

    def test_require_admin_allows_admin(self):
        from monitor.decorators import require_admin
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage
        factory = RequestFactory()
        req = factory.post('/fake/')
        req.user = self.admin
        req.session = self.client.session
        req._messages = FallbackStorage(req)

        @require_admin
        def my_view(request):
            return type('R', (), {'status_code': 200})()

        response = my_view(req)
        self.assertEqual(response.status_code, 200)

    def test_require_admin_rejects_viewer(self):
        from monitor.decorators import require_admin
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage
        factory = RequestFactory()
        req = factory.post('/fake/')
        req.user = self.viewer
        req.session = self.client.session
        req._messages = FallbackStorage(req)

        @require_admin
        def my_view(request):
            return type('R', (), {'status_code': 200})()

        response = my_view(req)
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::DecoratorTest -v --keepdb
```

Expected: FAIL — `monitor.decorators` not found.

- [ ] **Step 3: Create `monitor/decorators.py`**

```python
"""
monitor/decorators.py -- Shared auth/RBAC decorators for settings views.
"""
from functools import wraps

from django.http import HttpResponseForbidden


def require_admin(view_func):
    """
    Require that the logged-in user has role 'admin' or 'owner'.
    Must be used AFTER @login_required (assumes request.user is authenticated).
    Returns HTTP 403 for viewers and operators.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        try:
            role = request.user.profile.role
        except Exception:
            return HttpResponseForbidden("Admin access required.")
        if role not in ('admin', 'owner'):
            return HttpResponseForbidden("Admin access required.")
        return view_func(request, *args, **kwargs)
    return _wrapped


def is_htmx(request):
    """Return True if the request was made by HTMX."""
    return request.headers.get('HX-Request') == 'true'
```

- [ ] **Step 4: Create `monitor/forms.py`**

```python
"""
monitor/forms.py -- Django forms for settings pages.
"""
from django import forms

from monitor.models import AlertRule


SCOPE_CHOICES = [
    ('ingest', 'Ingest (write metrics)'),
    ('read', 'Read (query metrics)'),
]


class APIKeyCreateForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Production Agent'}),
    )
    scopes = forms.MultipleChoiceField(
        choices=SCOPE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        initial=['ingest'],
    )


class AlertRuleForm(forms.ModelForm):
    class Meta:
        model = AlertRule
        fields = ['name', 'metric', 'threshold_value', 'duration_seconds', 'slack_webhook_url']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. GPU Offline'}),
            'threshold_value': forms.NumberInput(attrs={'placeholder': 'e.g. 20'}),
            'duration_seconds': forms.NumberInput(),
            'slack_webhook_url': forms.URLInput(attrs={'placeholder': 'https://hooks.slack.com/…'}),
        }


class GPUClusterForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. prod-cluster-1'}),
    )


class GPUClusterRenameForm(forms.Form):
    name = forms.CharField(max_length=255)


class InferenceEndpointForm(forms.Form):
    ENGINE_CHOICES = [
        ('vllm', 'vLLM'),
        ('triton', 'Triton'),
        ('tgi', 'TGI'),
        ('other', 'Other'),
    ]
    name = forms.CharField(max_length=255)
    engine = forms.ChoiceField(choices=ENGINE_CHOICES)
    url = forms.URLField(required=False, widget=forms.URLInput(attrs={'placeholder': 'http://…'}))


class InviteForm(forms.Form):
    ROLE_CHOICES = [
        ('viewer', 'Viewer'),
        ('admin', 'Admin'),
        ('owner', 'Owner'),
    ]
    email = forms.EmailField(widget=forms.EmailInput(attrs={'placeholder': 'colleague@company.com'}))
    role = forms.ChoiceField(choices=ROLE_CHOICES)


class AcceptInviteForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirm = forms.CharField(widget=forms.PasswordInput, label='Confirm password')

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get('password')
        pw2 = cleaned.get('password_confirm')
        if pw and pw2 and pw != pw2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned
```

- [ ] **Step 5: Run tests and verify they pass**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::DecoratorTest -v --keepdb
```

Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add monitor/decorators.py monitor/forms.py
git commit -m "feat: add require_admin decorator and settings forms"
```

---

### Task 4: Settings Layout — base.html + settings_base.html + URL skeleton

**Files:**
- Modify: `monitor/templates/monitor/base.html`
- Create: `monitor/templates/monitor/settings_base.html`
- Modify: `monitor/urls.py`
- Create: `monitor/views/settings_views.py` (skeleton only)

- [ ] **Step 1: Write the failing test**

```python
# Add to monitor/tests/test_settings_views.py

class SettingsNavTest(TestCase):
    def setUp(self):
        self.user, self.org = _make_user_and_org('nav_user', role='admin')
        self.client.login(username='nav_user', password='pw')

    def test_settings_redirect_to_api_keys(self):
        response = self.client.get('/settings/')
        self.assertRedirects(response, '/settings/api-keys/', fetch_redirect_response=False)

    def test_api_keys_page_returns_200(self):
        response = self.client.get('/settings/api-keys/')
        self.assertEqual(response.status_code, 200)

    def test_alert_rules_page_returns_200(self):
        response = self.client.get('/settings/alert-rules/')
        self.assertEqual(response.status_code, 200)

    def test_resources_page_returns_200(self):
        response = self.client.get('/settings/resources/')
        self.assertEqual(response.status_code, 200)

    def test_members_page_returns_200(self):
        response = self.client.get('/settings/members/')
        self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::SettingsNavTest -v --keepdb
```

Expected: FAIL — `/settings/` returns 404.

- [ ] **Step 3: Update `monitor/templates/monitor/base.html`**

Find the closing `</nav>` or nav area in base.html. Add the following before the closing tag of the top nav bar:

1. Load HTMX from CDN — add in `<head>`:
```html
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
```

2. Add CSRF meta tag in `<head>` (for HTMX POST):
```html
<meta name="csrf-token" content="{{ csrf_token }}">
```

3. Add HTMX CSRF config + error toast script just before `</body>`:
```html
<script>
  document.body.addEventListener('htmx:configRequest', function(e) {
    e.detail.headers['X-CSRFToken'] = document.querySelector('meta[name=csrf-token]').content;
  });
  document.body.addEventListener('htmx:responseError', function(e) {
    const toast = document.createElement('div');
    toast.textContent = 'Action failed. Please try again.';
    toast.style = 'position:fixed;bottom:20px;right:20px;background:#f87171;color:#000;padding:10px 16px;border-radius:6px;font-size:.8rem;z-index:9999';
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  });
</script>
```

4. Add Settings nav link and user/logout in the nav bar. Find the existing nav links and add:
```html
{% if request.user.is_authenticated %}
<a href="/settings/" style="color:#94a3b8;text-decoration:none;font-size:.8rem;margin-left:16px">⚙ Settings</a>
<span style="color:#475569;margin-left:16px;font-size:.8rem">{{ request.user.username }}</span>
<a href="/accounts/logout/" style="color:#64748b;text-decoration:none;font-size:.75rem;margin-left:8px">Logout</a>
{% endif %}
```

- [ ] **Step 4: Create `monitor/templates/monitor/settings_base.html`**

```html
{% extends "monitor/base.html" %}
{% block content %}
<div style="display:flex;min-height:calc(100vh - 60px)">

  <!-- Sidebar -->
  <nav style="width:180px;border-right:1px solid #1e293b;padding:20px 0;flex-shrink:0;background:#0f172a">
    <div style="padding:0 16px 12px;font-size:.65rem;font-family:monospace;text-transform:uppercase;letter-spacing:.1em;color:#475569">Settings</div>
    <a href="/settings/api-keys/"
       style="display:block;padding:8px 16px;font-size:.78rem;text-decoration:none;
              {% if active_tab == 'api-keys' %}background:rgba(118,185,0,.08);border-left:2px solid #76B900;color:#e2e8f0{% else %}color:#64748b;border-left:2px solid transparent{% endif %}">
      🔑 API Keys
    </a>
    <a href="/settings/alert-rules/"
       style="display:block;padding:8px 16px;font-size:.78rem;text-decoration:none;
              {% if active_tab == 'alert-rules' %}background:rgba(118,185,0,.08);border-left:2px solid #76B900;color:#e2e8f0{% else %}color:#64748b;border-left:2px solid transparent{% endif %}">
      🔔 Alert Rules
    </a>
    <a href="/settings/resources/"
       style="display:block;padding:8px 16px;font-size:.78rem;text-decoration:none;
              {% if active_tab == 'resources' %}background:rgba(118,185,0,.08);border-left:2px solid #76B900;color:#e2e8f0{% else %}color:#64748b;border-left:2px solid transparent{% endif %}">
      🖥 Resources
    </a>
    <a href="/settings/members/"
       style="display:block;padding:8px 16px;font-size:.78rem;text-decoration:none;
              {% if active_tab == 'members' %}background:rgba(118,185,0,.08);border-left:2px solid #76B900;color:#e2e8f0{% else %}color:#64748b;border-left:2px solid transparent{% endif %}">
      👥 Members
    </a>
  </nav>

  <!-- Content area -->
  <div style="flex:1;padding:28px;overflow-y:auto">
    {% block settings_content %}{% endblock %}
  </div>

</div>
{% endblock %}
```

- [ ] **Step 5: Create skeleton `monitor/views/settings_views.py`**

```python
"""
monitor/views/settings_views.py -- Settings management views (API Keys, Alert Rules, Resources, Members).
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


def _get_org(user):
    """Return the organization for the logged-in user, or None."""
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
    org = _get_org(request.user)
    return render(request, 'monitor/settings_api_keys.html', {
        'active_tab': 'api-keys',
        'org': org,
        'is_admin': _is_admin(request.user),
        'api_keys': org.api_keys.all() if org else [],
    })


@login_required
def settings_alert_rules(request):
    org = _get_org(request.user)
    return render(request, 'monitor/settings_alert_rules.html', {
        'active_tab': 'alert-rules',
        'org': org,
        'is_admin': _is_admin(request.user),
        'rules': org.alert_rules.all() if org else [],
    })


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
def settings_members(request):
    org = _get_org(request.user)
    from monitor.models import Invite
    members = org.get_members() if org else []
    pending = Invite.objects.filter(organization=org, accepted_at__isnull=True) if org else []
    return render(request, 'monitor/settings_members.html', {
        'active_tab': 'members',
        'org': org,
        'is_admin': _is_admin(request.user),
        'members': members,
        'pending_invites': pending,
    })


def accept_invite(request, token):
    return render(request, 'monitor/accept_invite.html', {})
```

- [ ] **Step 6: Add settings URLs to `monitor/urls.py`**

```python
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

    # ── REST API ──────────────────────────────────────────────────────────────
    path('api/v1/ingest/gpu/', ingest_gpu, name='api_ingest_gpu'),
    path('api/v1/ingest/inference/', ingest_inference, name='api_ingest_inference'),

    # ── Settings ──────────────────────────────────────────────────────────────
    path('settings/', settings_root, name='settings_root'),
    path('settings/api-keys/', settings_api_keys, name='settings_api_keys'),
    path('settings/alert-rules/', settings_alert_rules, name='settings_alert_rules'),
    path('settings/resources/', settings_resources, name='settings_resources'),
    path('settings/members/', settings_members, name='settings_members'),
]
```

- [ ] **Step 7: Create stub templates for the four pages**

Create `monitor/templates/monitor/settings_api_keys.html`:
```html
{% extends "monitor/settings_base.html" %}
{% block settings_content %}
<h2 style="font-family:monospace;color:#e2e8f0;font-size:.95rem;margin-bottom:4px">API Keys</h2>
<p style="color:#64748b;font-size:.72rem;margin-bottom:20px">API keys stub</p>
{% endblock %}
```

Create `monitor/templates/monitor/settings_alert_rules.html`:
```html
{% extends "monitor/settings_base.html" %}
{% block settings_content %}
<h2 style="font-family:monospace;color:#e2e8f0;font-size:.95rem;margin-bottom:4px">Alert Rules</h2>
<p style="color:#64748b;font-size:.72rem;margin-bottom:20px">Alert rules stub</p>
{% endblock %}
```

Create `monitor/templates/monitor/settings_resources.html`:
```html
{% extends "monitor/settings_base.html" %}
{% block settings_content %}
<h2 style="font-family:monospace;color:#e2e8f0;font-size:.95rem;margin-bottom:4px">Resources</h2>
<p style="color:#64748b;font-size:.72rem;margin-bottom:20px">Resources stub</p>
{% endblock %}
```

Create `monitor/templates/monitor/settings_members.html`:
```html
{% extends "monitor/settings_base.html" %}
{% block settings_content %}
<h2 style="font-family:monospace;color:#e2e8f0;font-size:.95rem;margin-bottom:4px">Members</h2>
<p style="color:#64748b;font-size:.72rem;margin-bottom:20px">Members stub</p>
{% endblock %}
```

- [ ] **Step 8: Run tests and verify they pass**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::SettingsNavTest -v --keepdb
```

Expected: PASS (5 tests)

- [ ] **Step 9: Commit**

```bash
git add monitor/templates/monitor/base.html \
        monitor/templates/monitor/settings_base.html \
        monitor/templates/monitor/settings_api_keys.html \
        monitor/templates/monitor/settings_alert_rules.html \
        monitor/templates/monitor/settings_resources.html \
        monitor/templates/monitor/settings_members.html \
        monitor/views/settings_views.py monitor/urls.py monitor/urls_accounts.py
git commit -m "feat: settings layout skeleton — sidebar, nav link, stub pages, URL wiring"
```

---

### Task 5: API Keys Page

**Files:**
- Modify: `monitor/views/settings_views.py` (expand `settings_api_keys` + add `revoke_api_key`)
- Modify: `monitor/urls.py` (add revoke URL)
- Modify: `monitor/templates/monitor/settings_api_keys.html` (full template)

- [ ] **Step 1: Write the failing test**

```python
# Add to monitor/tests/test_settings_views.py

class APIKeysPageTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('api_admin', role='owner')
        self.viewer = User.objects.create_user(username='api_viewer', password='pw')
        self.viewer.profile.organization = self.org
        self.viewer.profile.role = 'viewer'
        self.viewer.profile.save()

    def test_create_api_key_returns_raw_key_in_context(self):
        self.client.login(username='api_admin', password='pw')
        response = self.client.post('/settings/api-keys/', {
            'name': 'Test Key',
            'scopes': ['ingest'],
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('new_raw_key', response.context)
        self.assertIsNotNone(response.context['new_raw_key'])

    def test_create_api_key_viewer_gets_403(self):
        self.client.login(username='api_viewer', password='pw')
        response = self.client.post('/settings/api-keys/', {
            'name': 'Test Key',
            'scopes': ['ingest'],
        })
        self.assertEqual(response.status_code, 403)

    def test_revoke_sets_active_false(self):
        from monitor.models import APIKey
        self.client.login(username='api_admin', password='pw')
        api_key, _ = APIKey.create_key(self.org, self.admin, 'ToRevoke', ['ingest'])
        response = self.client.post(f'/settings/api-keys/{api_key.id}/revoke/')
        self.assertEqual(response.status_code, 200)
        api_key.refresh_from_db()
        self.assertFalse(api_key.active)

    def test_revoke_viewer_gets_403(self):
        from monitor.models import APIKey
        self.client.login(username='api_viewer', password='pw')
        api_key, _ = APIKey.create_key(self.org, self.admin, 'ToRevoke2', ['ingest'])
        response = self.client.post(f'/settings/api-keys/{api_key.id}/revoke/')
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::APIKeysPageTest -v --keepdb
```

Expected: FAIL — revoke URL 404, create not implemented yet.

- [ ] **Step 3: Expand `settings_api_keys` and add `revoke_api_key` in `settings_views.py`**

Replace the `settings_api_keys` stub with:

```python
@login_required
def settings_api_keys(request):
    org = _get_org(request.user)
    is_admin = _is_admin(request.user)
    new_raw_key = None

    if request.method == 'POST':
        if not is_admin:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Admin access required.")
        from monitor.forms import APIKeyCreateForm
        form = APIKeyCreateForm(request.POST)
        if form.is_valid():
            from monitor.models import APIKey
            api_key, new_raw_key = APIKey.create_key(
                organization=org,
                user=request.user,
                name=form.cleaned_data['name'],
                scopes=form.cleaned_data['scopes'],
            )
    else:
        from monitor.forms import APIKeyCreateForm
        form = APIKeyCreateForm()

    return render(request, 'monitor/settings_api_keys.html', {
        'active_tab': 'api-keys',
        'org': org,
        'is_admin': is_admin,
        'api_keys': org.api_keys.all() if org else [],
        'form': form,
        'new_raw_key': new_raw_key,
    })
```

Add the revoke view after `settings_api_keys`:

```python
@login_required
@require_admin
def revoke_api_key(request, key_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import APIKey
    from monitor.decorators import is_htmx as _is_htmx
    org = _get_org(request.user)
    api_key = get_object_or_404(APIKey, pk=key_id, organization=org)
    if request.method == 'POST':
        api_key.active = False
        api_key.save(update_fields=['active'])
    # Return fragment for HTMX; full page redirect otherwise
    if _is_htmx(request):
        return render(request, 'monitor/fragments/api_key_row.html', {'key': api_key, 'is_admin': True})
    return redirect('/settings/api-keys/')
```

Add the import at the top of `settings_views.py`:
```python
from monitor.decorators import require_admin
```

- [ ] **Step 4: Add revoke URL to `monitor/urls.py`**

Add after the existing settings URLs:
```python
from monitor.views.settings_views import revoke_api_key

# inside urlpatterns:
path('settings/api-keys/<uuid:key_id>/revoke/', revoke_api_key, name='revoke_api_key'),
```

- [ ] **Step 5: Create HTMX fragment `monitor/templates/monitor/fragments/api_key_row.html`**

```html
<tr id="api-key-{{ key.id }}" style="border-bottom:1px solid #1e293b;opacity:.5">
  <td style="padding:9px 10px;color:#94a3b8;font-family:monospace;font-size:.78rem">{{ key.key_prefix }}…</td>
  <td style="padding:9px 10px;color:#94a3b8">{{ key.name }}</td>
  <td style="padding:9px 10px">
    {% for s in key.scopes %}<span style="background:#1e293b;color:#64748b;font-size:.62rem;padding:2px 7px;border-radius:10px;margin-right:4px">{{ s }}</span>{% endfor %}
  </td>
  <td style="padding:9px 10px;color:#64748b;font-size:.72rem">{{ key.last_used_at|default:"never" }}</td>
  <td style="padding:9px 10px">
    <span style="background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.25);color:#f87171;font-size:.62rem;padding:2px 7px;border-radius:10px">revoked</span>
  </td>
  <td style="padding:9px 10px"></td>
</tr>
```

- [ ] **Step 6: Build out the full `settings_api_keys.html` template**

```html
{% extends "monitor/settings_base.html" %}
{% block settings_content %}
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
  <div>
    <h2 style="font-family:monospace;color:#e2e8f0;font-size:.95rem;margin:0 0 4px 0">API Keys</h2>
    <p style="color:#64748b;font-size:.72rem;margin:0">Keys for programmatic access (Go agent, CI pipelines)</p>
  </div>
</div>

{% if new_raw_key %}
<div style="background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.3);border-radius:6px;padding:14px;margin-bottom:20px">
  <div style="font-size:.75rem;font-weight:700;color:#fbbf24;margin-bottom:6px">⚠ Copy this key now — it will not be shown again</div>
  <code style="font-family:monospace;font-size:.82rem;color:#e2e8f0;background:#1e293b;padding:8px 14px;border-radius:4px;display:block;word-break:break-all">{{ new_raw_key }}</code>
</div>
{% endif %}

<table style="width:100%;border-collapse:collapse;font-size:.78rem;margin-bottom:28px">
  <thead>
    <tr style="border-bottom:1px solid #1e293b">
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Prefix</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Name</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Scopes</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Last Used</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Status</th>
      <th style="padding:8px 10px"></th>
    </tr>
  </thead>
  <tbody>
  {% for key in api_keys %}
    <tr id="api-key-{{ key.id }}" style="border-bottom:1px solid #1e293b{% if not key.active %};opacity:.5{% endif %}">
      <td style="padding:9px 10px;color:#94a3b8;font-family:monospace;font-size:.78rem">{{ key.key_prefix }}…</td>
      <td style="padding:9px 10px;color:#e2e8f0">{{ key.name }}</td>
      <td style="padding:9px 10px">
        {% for s in key.scopes %}<span style="background:#1e293b;color:#64748b;font-size:.62rem;padding:2px 7px;border-radius:10px;margin-right:4px">{{ s }}</span>{% endfor %}
      </td>
      <td style="padding:9px 10px;color:#64748b;font-size:.72rem">{{ key.last_used_at|default:"never" }}</td>
      <td style="padding:9px 10px">
        {% if key.active %}
        <span style="background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.2);color:#4ade80;font-size:.62rem;padding:2px 7px;border-radius:10px">active</span>
        {% else %}
        <span style="background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.25);color:#f87171;font-size:.62rem;padding:2px 7px;border-radius:10px">revoked</span>
        {% endif %}
      </td>
      <td style="padding:9px 10px;text-align:right">
        {% if is_admin and key.active %}
        <button hx-post="/settings/api-keys/{{ key.id }}/revoke/"
                hx-target="#api-key-{{ key.id }}"
                hx-swap="outerHTML"
                style="background:transparent;border:none;color:#f87171;font-size:.72rem;cursor:pointer;padding:0">
          Revoke
        </button>
        {% endif %}
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="6" style="padding:20px 10px;color:#475569;text-align:center;font-size:.78rem">No API keys yet</td></tr>
  {% endfor %}
  </tbody>
</table>

{% if is_admin %}
<div style="background:#111827;border:1px solid #1e293b;border-radius:6px;padding:18px">
  <div style="font-size:.8rem;font-weight:700;color:#e2e8f0;font-family:monospace;margin-bottom:14px">Create API Key</div>
  <form method="post">
    {% csrf_token %}
    <div style="margin-bottom:12px">
      <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Name</label>
      {{ form.name }}
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">Scopes</label>
      {% for choice in form.scopes %}
      <label style="display:inline-flex;align-items:center;gap:6px;margin-right:16px;font-size:.78rem;color:#94a3b8;cursor:pointer">
        {{ choice.tag }} {{ choice.choice_label }}
      </label>
      {% endfor %}
    </div>
    <button type="submit" style="background:#76B900;color:#000;font-weight:700;font-family:monospace;font-size:.78rem;padding:7px 16px;border:none;border-radius:4px;cursor:pointer">
      Create Key
    </button>
  </form>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 7: Run tests and verify they pass**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::APIKeysPageTest -v --keepdb
```

Expected: PASS (4 tests)

- [ ] **Step 8: Commit**

```bash
git add monitor/views/settings_views.py monitor/urls.py \
        monitor/templates/monitor/settings_api_keys.html \
        monitor/templates/monitor/fragments/
git commit -m "feat: API keys settings page — list, create, HTMX revoke"
```

---

### Task 6: Alert Rules Settings Page

**Files:**
- Modify: `monitor/views/settings_views.py` (add alert rule CRUD views)
- Modify: `monitor/urls.py` (alert rule URLs)
- Modify: `monitor/templates/monitor/settings_alert_rules.html` (full template)
- Create: `monitor/templates/monitor/fragments/alert_rule_toggle.html`

- [ ] **Step 1: Write the failing test**

```python
# Add to monitor/tests/test_settings_views.py

class AlertRulesPageTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('ar_admin', role='owner')
        self.viewer = User.objects.create_user(username='ar_viewer', password='pw')
        self.viewer.profile.organization = self.org
        self.viewer.profile.role = 'viewer'
        self.viewer.profile.save()
        from monitor.models import AlertRule
        self.rule = AlertRule.objects.create(
            organization=self.org,
            name='Test Rule',
            metric='gpu_utilization_low',
            threshold_value=20.0,
            is_enabled=True,
        )

    def test_create_alert_rule(self):
        self.client.login(username='ar_admin', password='pw')
        response = self.client.post('/settings/alert-rules/create/', {
            'name': 'New Rule',
            'metric': 'gpu_offline',
            'threshold_value': '0',
            'duration_seconds': '300',
            'slack_webhook_url': '',
        })
        self.assertEqual(response.status_code, 302)
        from monitor.models import AlertRule
        self.assertTrue(AlertRule.objects.filter(name='New Rule', organization=self.org).exists())

    def test_create_alert_rule_viewer_gets_403(self):
        self.client.login(username='ar_viewer', password='pw')
        response = self.client.post('/settings/alert-rules/create/', {
            'name': 'X', 'metric': 'gpu_offline', 'threshold_value': '0',
            'duration_seconds': '300', 'slack_webhook_url': '',
        })
        self.assertEqual(response.status_code, 403)

    def test_toggle_alert_rule(self):
        self.client.login(username='ar_admin', password='pw')
        response = self.client.post(f'/settings/alert-rules/{self.rule.id}/toggle/')
        self.assertEqual(response.status_code, 200)
        self.rule.refresh_from_db()
        self.assertFalse(self.rule.is_enabled)

    def test_delete_alert_rule(self):
        self.client.login(username='ar_admin', password='pw')
        response = self.client.post(f'/settings/alert-rules/{self.rule.id}/delete/')
        self.assertEqual(response.status_code, 200)
        from monitor.models import AlertRule
        self.assertFalse(AlertRule.objects.filter(pk=self.rule.id).exists())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::AlertRulesPageTest -v --keepdb
```

Expected: FAIL — alert rule URLs 404.

- [ ] **Step 3: Add alert rule views to `settings_views.py`**

```python
@login_required
def settings_alert_rules(request):
    org = _get_org(request.user)
    from monitor.forms import AlertRuleForm
    form = AlertRuleForm()
    return render(request, 'monitor/settings_alert_rules.html', {
        'active_tab': 'alert-rules',
        'org': org,
        'is_admin': _is_admin(request.user),
        'rules': org.alert_rules.all() if org else [],
        'form': form,
    })


@login_required
@require_admin
def create_alert_rule(request):
    if request.method != 'POST':
        return redirect('/settings/alert-rules/')
    org = _get_org(request.user)
    from monitor.forms import AlertRuleForm
    form = AlertRuleForm(request.POST)
    if form.is_valid():
        rule = form.save(commit=False)
        rule.organization = org
        rule.save()
    return redirect('/settings/alert-rules/')


@login_required
@require_admin
def edit_alert_rule(request, rule_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import AlertRule
    from monitor.forms import AlertRuleForm
    org = _get_org(request.user)
    rule = get_object_or_404(AlertRule, pk=rule_id, organization=org)
    if request.method == 'POST':
        form = AlertRuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
        return redirect('/settings/alert-rules/')
    form = AlertRuleForm(instance=rule)
    from monitor.decorators import is_htmx as _is_htmx
    if _is_htmx(request):
        return render(request, 'monitor/fragments/alert_rule_form.html', {'form': form, 'rule': rule})
    return redirect('/settings/alert-rules/')


@login_required
@require_admin
def toggle_alert_rule(request, rule_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import AlertRule
    org = _get_org(request.user)
    rule = get_object_or_404(AlertRule, pk=rule_id, organization=org)
    if request.method == 'POST':
        rule.is_enabled = not rule.is_enabled
        rule.save(update_fields=['is_enabled'])
    return render(request, 'monitor/fragments/alert_rule_toggle.html', {
        'rule': rule, 'is_admin': True,
    })


@login_required
@require_admin
def delete_alert_rule(request, rule_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import AlertRule
    org = _get_org(request.user)
    rule = get_object_or_404(AlertRule, pk=rule_id, organization=org)
    if request.method == 'POST':
        rule.delete()
    return HttpResponse('')
```

Add `from django.http import HttpResponse` to the top of `settings_views.py`.

- [ ] **Step 4: Add alert rule URLs to `monitor/urls.py`**

```python
from monitor.views.settings_views import (
    settings_root, settings_api_keys, revoke_api_key,
    settings_alert_rules, create_alert_rule, edit_alert_rule,
    toggle_alert_rule, delete_alert_rule,
    settings_resources, settings_members,
)

# add to urlpatterns:
path('settings/alert-rules/create/', create_alert_rule, name='create_alert_rule'),
path('settings/alert-rules/<int:rule_id>/edit/', edit_alert_rule, name='edit_alert_rule'),
path('settings/alert-rules/<int:rule_id>/toggle/', toggle_alert_rule, name='toggle_alert_rule'),
path('settings/alert-rules/<int:rule_id>/delete/', delete_alert_rule, name='delete_alert_rule'),
```

- [ ] **Step 5: Create `monitor/templates/monitor/fragments/alert_rule_toggle.html`**

```html
{% if rule.is_enabled %}
<span id="toggle-{{ rule.id }}"
      hx-post="/settings/alert-rules/{{ rule.id }}/toggle/"
      hx-target="#toggle-{{ rule.id }}"
      hx-swap="outerHTML"
      style="display:inline-flex;align-items:center;gap:5px;font-size:.68rem;font-family:monospace;padding:3px 10px;border-radius:12px;background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.25);color:#4ade80;cursor:pointer">● ON</span>
{% else %}
<span id="toggle-{{ rule.id }}"
      hx-post="/settings/alert-rules/{{ rule.id }}/toggle/"
      hx-target="#toggle-{{ rule.id }}"
      hx-swap="outerHTML"
      style="display:inline-flex;align-items:center;gap:5px;font-size:.68rem;font-family:monospace;padding:3px 10px;border-radius:12px;background:rgba(100,116,139,.1);border:1px solid rgba(100,116,139,.25);color:#64748b;cursor:pointer">○ OFF</span>
{% endif %}
```

- [ ] **Step 6: Build the full `settings_alert_rules.html` template**

```html
{% extends "monitor/settings_base.html" %}
{% block settings_content %}
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
  <div>
    <h2 style="font-family:monospace;color:#e2e8f0;font-size:.95rem;margin:0 0 4px 0">Alert Rules</h2>
    <p style="color:#64748b;font-size:.72rem;margin:0">Threshold-based alerts with optional Slack notifications</p>
  </div>
  {% if is_admin %}
  <button onclick="document.getElementById('rule-form').style.display='block'"
          style="background:#76B900;color:#000;font-weight:700;font-family:monospace;font-size:.75rem;padding:6px 14px;border:none;border-radius:4px;cursor:pointer">
    + New Rule
  </button>
  {% endif %}
</div>

<table style="width:100%;border-collapse:collapse;font-size:.78rem;margin-bottom:24px">
  <thead>
    <tr style="border-bottom:1px solid #1e293b">
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Name</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Metric</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Threshold</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Slack</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Enabled</th>
      <th style="padding:8px 10px"></th>
    </tr>
  </thead>
  <tbody>
  {% for rule in rules %}
    <tr id="rule-row-{{ rule.id }}" style="border-bottom:1px solid #1e293b">
      <td style="padding:9px 10px;color:#e2e8f0">{{ rule.name }}</td>
      <td style="padding:9px 10px;color:#94a3b8;font-family:monospace;font-size:.72rem">{{ rule.metric }}</td>
      <td style="padding:9px 10px;color:#94a3b8">{{ rule.threshold_value }}</td>
      <td style="padding:9px 10px">
        {% if rule.slack_webhook_url %}
        <span style="color:#4ade80;font-size:.72rem">✓ set</span>
        {% else %}
        <span style="color:#64748b;font-size:.72rem">— none</span>
        {% endif %}
      </td>
      <td style="padding:9px 10px">
        {% include "monitor/fragments/alert_rule_toggle.html" with rule=rule is_admin=is_admin %}
      </td>
      <td style="padding:9px 10px;text-align:right">
        {% if is_admin %}
        <span style="display:inline-flex;gap:10px">
          <button hx-get="/settings/alert-rules/{{ rule.id }}/edit/"
                  hx-target="#rule-form"
                  hx-swap="innerHTML"
                  onclick="document.getElementById('rule-form').style.display='block'"
                  style="background:transparent;border:none;color:#60a5fa;font-size:.72rem;cursor:pointer;padding:0">Edit</button>
          <button hx-post="/settings/alert-rules/{{ rule.id }}/delete/"
                  hx-target="#rule-row-{{ rule.id }}"
                  hx-swap="outerHTML"
                  hx-confirm="Delete rule '{{ rule.name }}'?"
                  style="background:transparent;border:none;color:#f87171;font-size:.72rem;cursor:pointer;padding:0">Delete</button>
        </span>
        {% endif %}
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="6" style="padding:20px 10px;color:#475569;text-align:center;font-size:.78rem">No alert rules yet</td></tr>
  {% endfor %}
  </tbody>
</table>

{% if is_admin %}
<div id="rule-form" style="display:none;background:#111827;border:1px solid #1e293b;border-radius:6px;padding:18px">
  <div style="font-size:.8rem;font-weight:700;color:#e2e8f0;font-family:monospace;margin-bottom:14px">New Rule</div>
  <form method="post" action="/settings/alert-rules/create/">
    {% csrf_token %}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
      <div>
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Name</label>
        {{ form.name }}
      </div>
      <div>
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Metric</label>
        {{ form.metric }}
      </div>
      <div>
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Threshold</label>
        {{ form.threshold_value }}
      </div>
      <div>
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Duration (seconds)</label>
        {{ form.duration_seconds }}
      </div>
      <div style="grid-column:1/-1">
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Slack Webhook URL (optional)</label>
        {{ form.slack_webhook_url }}
      </div>
    </div>
    <div style="display:flex;gap:10px">
      <button type="submit" style="background:#76B900;color:#000;font-weight:700;font-family:monospace;font-size:.78rem;padding:7px 16px;border:none;border-radius:4px;cursor:pointer">Save Rule</button>
      <button type="button" onclick="document.getElementById('rule-form').style.display='none'"
              style="background:transparent;border:1px solid #334155;color:#64748b;font-size:.78rem;padding:7px 14px;border-radius:4px;cursor:pointer">Cancel</button>
    </div>
  </form>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 7: Run tests and verify they pass**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::AlertRulesPageTest -v --keepdb
```

Expected: PASS (4 tests)

- [ ] **Step 8: Commit**

```bash
git add monitor/views/settings_views.py monitor/urls.py \
        monitor/templates/monitor/settings_alert_rules.html \
        monitor/templates/monitor/fragments/alert_rule_toggle.html
git commit -m "feat: alert rules settings page — create, edit, toggle, delete"
```

---

### Task 7: Resources Settings Page

**Files:**
- Modify: `monitor/views/settings_views.py` (cluster/node/endpoint CRUD)
- Modify: `monitor/urls.py` (resource URLs)
- Modify: `monitor/templates/monitor/settings_resources.html` (full template)
- Modify: `monitor/models/inference.py` (verify `is_active` field exists)

- [ ] **Step 1: Verify InferenceEndpoint.is_active exists**

```bash
grep -n "is_active" /home/zeus/Desktop/dev/github/gpuwatch/monitor/models/inference.py
```

Expected: a line showing `is_active = models.BooleanField(...)`. If missing, add it and create a migration. (Based on spec it already exists — verify before proceeding.)

- [ ] **Step 2: Write the failing test**

```python
# Add to monitor/tests/test_settings_views.py

class ResourcesPageTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('res_admin', role='owner')
        self.viewer = User.objects.create_user(username='res_viewer', password='pw')
        self.viewer.profile.organization = self.org
        self.viewer.profile.role = 'viewer'
        self.viewer.profile.save()

    def test_create_cluster(self):
        self.client.login(username='res_admin', password='pw')
        response = self.client.post('/settings/resources/clusters/create/', {'name': 'prod-cluster'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GPUCluster.objects_unscoped.filter(name='prod-cluster', organization=self.org).exists())

    def test_deactivate_cluster(self):
        self.client.login(username='res_admin', password='pw')
        cluster = GPUCluster.objects_unscoped.create(organization=self.org, name='to-deactivate')
        response = self.client.post(f'/settings/resources/clusters/{cluster.id}/deactivate/')
        self.assertEqual(response.status_code, 200)
        cluster.refresh_from_db()
        self.assertFalse(cluster.is_active)

    def test_deactivate_cluster_viewer_gets_403(self):
        self.client.login(username='res_viewer', password='pw')
        cluster = GPUCluster.objects_unscoped.create(organization=self.org, name='cluster-v')
        response = self.client.post(f'/settings/resources/clusters/{cluster.id}/deactivate/')
        self.assertEqual(response.status_code, 403)

    def test_delete_cluster(self):
        self.client.login(username='res_admin', password='pw')
        cluster = GPUCluster.objects_unscoped.create(organization=self.org, name='to-delete')
        response = self.client.post(f'/settings/resources/clusters/{cluster.id}/delete/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GPUCluster.objects_unscoped.filter(pk=cluster.id).exists())
```

- [ ] **Step 3: Run test to verify it fails**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::ResourcesPageTest -v --keepdb
```

Expected: FAIL — resource URLs 404.

- [ ] **Step 4: Add resource views to `settings_views.py`**

```python
# ── Clusters ──────────────────────────────────────────────────────────────────

@login_required
@require_admin
def create_cluster(request):
    if request.method != 'POST':
        return redirect('/settings/resources/')
    org = _get_org(request.user)
    from monitor.forms import GPUClusterForm
    form = GPUClusterForm(request.POST)
    if form.is_valid():
        from monitor.models import GPUCluster
        GPUCluster.objects_unscoped.create(organization=org, name=form.cleaned_data['name'])
    return redirect('/settings/resources/')


@login_required
@require_admin
def rename_cluster(request, cluster_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import GPUCluster
    from monitor.decorators import is_htmx as _is_htmx
    org = _get_org(request.user)
    cluster = get_object_or_404(GPUCluster, pk=cluster_id, organization=org)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            cluster.name = name
            cluster.save(update_fields=['name'])
    if _is_htmx(request):
        return HttpResponse(f'<span style="font-family:monospace;color:#e2e8f0">{cluster.name}</span>')
    return redirect('/settings/resources/')


@login_required
@require_admin
def deactivate_cluster(request, cluster_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import GPUCluster
    org = _get_org(request.user)
    cluster = get_object_or_404(GPUCluster, pk=cluster_id, organization=org)
    if request.method == 'POST':
        cluster.is_active = False
        cluster.save(update_fields=['is_active'])
    return HttpResponse('<span style="background:rgba(100,116,139,.1);border:1px solid #475569;color:#64748b;font-size:.62rem;padding:2px 7px;border-radius:10px">inactive</span>')


@login_required
@require_admin
def delete_cluster(request, cluster_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import GPUCluster
    org = _get_org(request.user)
    cluster = get_object_or_404(GPUCluster, pk=cluster_id, organization=org)
    if request.method == 'POST':
        cluster.delete()
    return HttpResponse('')


# ── Nodes ─────────────────────────────────────────────────────────────────────

@login_required
@require_admin
def deactivate_node(request, node_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import GPUNode
    org = _get_org(request.user)
    node = get_object_or_404(GPUNode, pk=node_id, organization=org)
    if request.method == 'POST':
        node.is_active = False
        node.save(update_fields=['is_active'])
    return HttpResponse('<span style="background:rgba(100,116,139,.1);border:1px solid #475569;color:#64748b;font-size:.62rem;padding:2px 7px;border-radius:10px">inactive</span>')


@login_required
@require_admin
def delete_node(request, node_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import GPUNode
    org = _get_org(request.user)
    node = get_object_or_404(GPUNode, pk=node_id, organization=org)
    if request.method == 'POST':
        node.delete()
    return HttpResponse('')


# ── Inference Endpoints ───────────────────────────────────────────────────────

@login_required
@require_admin
def create_endpoint(request):
    if request.method != 'POST':
        return redirect('/settings/resources/?tab=endpoints')
    org = _get_org(request.user)
    from monitor.forms import InferenceEndpointForm
    form = InferenceEndpointForm(request.POST)
    if form.is_valid():
        from monitor.models import InferenceEndpoint
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
    from django.shortcuts import get_object_or_404
    from monitor.models import InferenceEndpoint
    org = _get_org(request.user)
    ep = get_object_or_404(InferenceEndpoint, pk=endpoint_id, organization=org)
    if request.method == 'POST':
        ep.is_active = False
        ep.save(update_fields=['is_active'])
    return HttpResponse('<span style="background:rgba(100,116,139,.1);border:1px solid #475569;color:#64748b;font-size:.62rem;padding:2px 7px;border-radius:10px">retired</span>')


@login_required
@require_admin
def delete_endpoint(request, endpoint_id):
    from django.shortcuts import get_object_or_404
    from monitor.models import InferenceEndpoint
    org = _get_org(request.user)
    ep = get_object_or_404(InferenceEndpoint, pk=endpoint_id, organization=org)
    if request.method == 'POST':
        ep.delete()
    return HttpResponse('')
```

- [ ] **Step 5: Add resource URLs to `monitor/urls.py`**

Import the new views and add to `urlpatterns`:

```python
from monitor.views.settings_views import (
    # ... existing imports ...
    create_cluster, rename_cluster, deactivate_cluster, delete_cluster,
    deactivate_node, delete_node,
    create_endpoint, deactivate_endpoint, delete_endpoint,
)

# add to urlpatterns:
path('settings/resources/clusters/create/', create_cluster, name='create_cluster'),
path('settings/resources/clusters/<uuid:cluster_id>/rename/', rename_cluster, name='rename_cluster'),
path('settings/resources/clusters/<uuid:cluster_id>/deactivate/', deactivate_cluster, name='deactivate_cluster'),
path('settings/resources/clusters/<uuid:cluster_id>/delete/', delete_cluster, name='delete_cluster'),
path('settings/resources/nodes/<uuid:node_id>/deactivate/', deactivate_node, name='deactivate_node'),
path('settings/resources/nodes/<uuid:node_id>/delete/', delete_node, name='delete_node'),
path('settings/resources/endpoints/create/', create_endpoint, name='create_endpoint'),
path('settings/resources/endpoints/<int:endpoint_id>/deactivate/', deactivate_endpoint, name='deactivate_endpoint'),
path('settings/resources/endpoints/<int:endpoint_id>/delete/', delete_endpoint, name='delete_endpoint'),
```

- [ ] **Step 6: Build the full `settings_resources.html` template**

```html
{% extends "monitor/settings_base.html" %}
{% block settings_content %}
<h2 style="font-family:monospace;color:#e2e8f0;font-size:.95rem;margin:0 0 4px 0">Resources</h2>
<p style="color:#64748b;font-size:.72rem;margin:0 0 18px 0">GPU clusters, nodes, and inference endpoints</p>

<!-- Tab switcher -->
<div style="display:flex;border-bottom:1px solid #1e293b;margin-bottom:18px">
  <a href="?tab=clusters"
     style="padding:7px 16px;font-size:.78rem;text-decoration:none;border-bottom:2px solid {% if tab == 'clusters' %}#76B900{% else %}transparent{% endif %};color:{% if tab == 'clusters' %}#e2e8f0{% else %}#64748b{% endif %}">
    Clusters &amp; Nodes
  </a>
  <a href="?tab=endpoints"
     style="padding:7px 16px;font-size:.78rem;text-decoration:none;border-bottom:2px solid {% if tab == 'endpoints' %}#76B900{% else %}transparent{% endif %};color:{% if tab == 'endpoints' %}#e2e8f0{% else %}#64748b{% endif %}">
    Inference Endpoints
  </a>
</div>

{% if tab == 'clusters' or not tab %}

  {% for cluster in clusters %}
  <div id="cluster-{{ cluster.id }}" style="background:#111827;border:1px solid #1e293b;border-radius:6px;padding:12px 14px;margin-bottom:10px">
    <div style="display:flex;align-items:center;justify-content:space-between">
      <div>
        <span style="font-family:monospace;color:#e2e8f0;font-size:.82rem">{{ cluster.name }}</span>
        <span style="margin-left:10px;color:#64748b;font-size:.68rem">{{ cluster.nodes.count }} node{{ cluster.nodes.count|pluralize }}</span>
      </div>
      {% if is_admin %}
      <div style="display:flex;gap:10px;font-size:.72rem">
        <button hx-post="/settings/resources/clusters/{{ cluster.id }}/deactivate/"
                hx-target="#cluster-status-{{ cluster.id }}"
                hx-swap="outerHTML"
                hx-confirm="Deactivate cluster '{{ cluster.name }}'?"
                style="background:transparent;border:none;color:#fbbf24;cursor:pointer;padding:0">Deactivate</button>
        <button hx-post="/settings/resources/clusters/{{ cluster.id }}/delete/"
                hx-target="#cluster-{{ cluster.id }}"
                hx-swap="outerHTML"
                hx-confirm="Hard delete cluster '{{ cluster.name }}' and all its data?"
                style="background:transparent;border:none;color:#f87171;cursor:pointer;padding:0">Delete</button>
      </div>
      {% endif %}
    </div>
    <span id="cluster-status-{{ cluster.id }}" style="display:none"></span>
    {% if cluster.nodes.all %}
    <div style="margin-top:10px;padding-top:10px;border-top:1px solid #1e293b">
      {% for node in cluster.nodes.all %}
      <div id="node-{{ node.id }}" style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
        <span style="font-family:monospace;color:#94a3b8;font-size:.75rem">↳ {{ node.hostname }}</span>
        <div style="display:flex;align-items:center;gap:10px;font-size:.7rem">
          <span style="background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.2);color:#4ade80;padding:1px 6px;border-radius:8px">{{ node.status }}</span>
          {% if is_admin %}
          <button hx-post="/settings/resources/nodes/{{ node.id }}/deactivate/"
                  hx-target="#node-{{ node.id }}"
                  hx-swap="innerHTML"
                  style="background:transparent;border:none;color:#fbbf24;cursor:pointer;padding:0">Deactivate</button>
          <button hx-post="/settings/resources/nodes/{{ node.id }}/delete/"
                  hx-target="#node-{{ node.id }}"
                  hx-swap="outerHTML"
                  hx-confirm="Delete node {{ node.hostname }}?"
                  style="background:transparent;border:none;color:#f87171;cursor:pointer;padding:0">Delete</button>
          {% endif %}
        </div>
      </div>
      {% endfor %}
    </div>
    {% endif %}
  </div>
  {% empty %}
    <p style="color:#475569;font-size:.78rem;margin-bottom:16px">No active clusters.</p>
  {% endfor %}

  {% if is_admin %}
  <form method="post" action="/settings/resources/clusters/create/" style="margin-top:14px;display:flex;gap:10px;align-items:flex-end">
    {% csrf_token %}
    <div>
      <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Cluster name</label>
      <input name="name" type="text" placeholder="e.g. prod-cluster-1"
             style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:7px 12px;border-radius:4px;font-size:.8rem">
    </div>
    <button type="submit" style="background:#76B900;color:#000;font-weight:700;font-family:monospace;font-size:.75rem;padding:7px 14px;border:none;border-radius:4px;cursor:pointer">
      + Add Cluster
    </button>
  </form>
  {% endif %}

{% else %}

  <table style="width:100%;border-collapse:collapse;font-size:.78rem;margin-bottom:20px">
    <thead>
      <tr style="border-bottom:1px solid #1e293b">
        <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Name</th>
        <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Engine</th>
        <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Status</th>
        <th style="padding:8px 10px"></th>
      </tr>
    </thead>
    <tbody>
    {% for ep in endpoints %}
      <tr id="ep-{{ ep.id }}" style="border-bottom:1px solid #1e293b">
        <td style="padding:9px 10px;color:#e2e8f0;font-family:monospace;font-size:.8rem">{{ ep.name }}</td>
        <td style="padding:9px 10px;color:#94a3b8">{{ ep.engine }}</td>
        <td id="ep-status-{{ ep.id }}" style="padding:9px 10px">
          <span style="background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.2);color:#4ade80;font-size:.62rem;padding:2px 7px;border-radius:10px">{{ ep.status }}</span>
        </td>
        <td style="padding:9px 10px;text-align:right">
          {% if is_admin %}
          <span style="display:inline-flex;gap:10px;font-size:.72rem">
            <button hx-post="/settings/resources/endpoints/{{ ep.id }}/deactivate/"
                    hx-target="#ep-status-{{ ep.id }}"
                    hx-swap="innerHTML"
                    hx-confirm="Deactivate endpoint '{{ ep.name }}'?"
                    style="background:transparent;border:none;color:#fbbf24;cursor:pointer;padding:0">Deactivate</button>
            <button hx-post="/settings/resources/endpoints/{{ ep.id }}/delete/"
                    hx-target="#ep-{{ ep.id }}"
                    hx-swap="outerHTML"
                    hx-confirm="Delete endpoint '{{ ep.name }}'?"
                    style="background:transparent;border:none;color:#f87171;cursor:pointer;padding:0">Delete</button>
          </span>
          {% endif %}
        </td>
      </tr>
    {% empty %}
      <tr><td colspan="4" style="padding:20px 10px;color:#475569;text-align:center;font-size:.78rem">No endpoints yet</td></tr>
    {% endfor %}
    </tbody>
  </table>

  {% if is_admin %}
  <div style="background:#111827;border:1px solid #1e293b;border-radius:6px;padding:16px;margin-top:10px">
    <div style="font-size:.8rem;font-weight:700;color:#e2e8f0;font-family:monospace;margin-bottom:12px">Add Endpoint</div>
    <form method="post" action="/settings/resources/endpoints/create/" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      {% csrf_token %}
      <div>
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Name</label>
        <input name="name" type="text" placeholder="e.g. prod-vllm"
               style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:7px 12px;border-radius:4px;font-size:.8rem">
      </div>
      <div>
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Engine</label>
        <select name="engine" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:7px 12px;border-radius:4px;font-size:.8rem">
          <option value="vllm">vLLM</option>
          <option value="triton">Triton</option>
          <option value="tgi">TGI</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div>
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">URL (optional)</label>
        <input name="url" type="url" placeholder="http://…"
               style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:7px 12px;border-radius:4px;font-size:.8rem;width:220px">
      </div>
      <button type="submit" style="background:#76B900;color:#000;font-weight:700;font-family:monospace;font-size:.75rem;padding:7px 14px;border:none;border-radius:4px;cursor:pointer">
        + Add
      </button>
    </form>
  </div>
  {% endif %}

{% endif %}
{% endblock %}
```

- [ ] **Step 7: Check that `InferenceEndpoint` has needed fields**

Read `monitor/models/inference.py` and confirm it has `name`, `engine`, `url`, `status`, `is_active`. Add any missing fields and a migration if needed. (The spec says `is_active` already exists.)

- [ ] **Step 8: Run tests and verify they pass**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::ResourcesPageTest -v --keepdb
```

Expected: PASS (4 tests)

- [ ] **Step 9: Commit**

```bash
git add monitor/views/settings_views.py monitor/urls.py \
        monitor/templates/monitor/settings_resources.html
git commit -m "feat: resources settings page — cluster/node/endpoint CRUD with HTMX"
```

---

### Task 8: Members + Invite Flow

**Files:**
- Modify: `monitor/views/settings_views.py` (member CRUD + invite views)
- Modify: `monitor/urls.py` (member + invite URLs)
- Modify: `monitor/templates/monitor/settings_members.html` (full template)
- Create: `monitor/templates/monitor/accept_invite.html` (full template)

- [ ] **Step 1: Write the failing test**

```python
# Add to monitor/tests/test_settings_views.py
from unittest.mock import patch


class MembersPageTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('mem_admin', role='owner')
        self.member = User.objects.create_user(username='mem_alice', password='pw')
        self.member.profile.organization = self.org
        self.member.profile.role = 'viewer'
        self.member.profile.save()

    @patch('django.core.mail.send_mail')
    def test_invite_creates_invite_row_and_sends_email(self, mock_send):
        self.client.login(username='mem_admin', password='pw')
        response = self.client.post('/settings/members/invite/', {
            'email': 'new@example.com',
            'role': 'viewer',
        })
        self.assertEqual(response.status_code, 302)
        from monitor.models import Invite
        self.assertTrue(Invite.objects.filter(email='new@example.com', organization=self.org).exists())
        self.assertTrue(mock_send.called)

    def test_change_member_role(self):
        self.client.login(username='mem_admin', password='pw')
        response = self.client.post(f'/settings/members/{self.member.id}/role/', {'role': 'admin'})
        self.assertEqual(response.status_code, 200)
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.role, 'admin')

    def test_remove_member(self):
        self.client.login(username='mem_admin', password='pw')
        response = self.client.post(f'/settings/members/{self.member.id}/remove/')
        self.assertEqual(response.status_code, 200)
        self.member.profile.refresh_from_db()
        self.assertIsNone(self.member.profile.organization)

    def test_accept_invite_creates_user(self):
        from monitor.models import Invite
        invite = Invite.objects.create(
            organization=self.org,
            invited_by=self.admin,
            email='newguy@example.com',
            role='viewer',
        )
        response = self.client.post(f'/accounts/accept-invite/{invite.token}/', {
            'username': 'newguy',
            'password': 'securepass123',
            'password_confirm': 'securepass123',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        new_user = User.objects.get(username='newguy')
        self.assertEqual(new_user.profile.organization, self.org)
        self.assertEqual(new_user.profile.role, 'viewer')
        invite.refresh_from_db()
        self.assertIsNotNone(invite.accepted_at)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::MembersPageTest -v --keepdb
```

Expected: FAIL — member/invite URLs 404.

- [ ] **Step 3: Add member and invite views to `settings_views.py`**

```python
@login_required
def settings_members(request):
    org = _get_org(request.user)
    from monitor.models import Invite
    from monitor.forms import InviteForm
    members = org.get_members().select_related('profile') if org else []
    pending = Invite.objects.filter(organization=org, accepted_at__isnull=True) if org else []
    form = InviteForm()
    return render(request, 'monitor/settings_members.html', {
        'active_tab': 'members',
        'org': org,
        'is_admin': _is_admin(request.user),
        'members': members,
        'pending_invites': pending,
        'form': form,
    })


@login_required
@require_admin
def change_member_role(request, user_id):
    from django.shortcuts import get_object_or_404
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
        f'{member.profile.role} ▾</span>'
    )


@login_required
@require_admin
def remove_member(request, user_id):
    from django.shortcuts import get_object_or_404
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
    from monitor.forms import InviteForm
    from monitor.models import Invite
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
    from django.shortcuts import get_object_or_404
    from monitor.models import Invite
    org = _get_org(request.user)
    invite = get_object_or_404(Invite, token=token, organization=org, accepted_at__isnull=True)
    if request.method == 'POST':
        invite.delete()
    return HttpResponse('')


@login_required
@require_admin
def resend_invite(request, token):
    from django.shortcuts import get_object_or_404
    from monitor.models import Invite
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
    return HttpResponse('<span style="color:#60a5fa;font-size:.68rem">Sent ✓</span>')


def accept_invite(request, token):
    from django.shortcuts import get_object_or_404
    from monitor.models import Invite
    from monitor.forms import AcceptInviteForm
    from django.contrib.auth import login
    from django.contrib.auth.models import User as DjangoUser
    from django.utils import timezone as tz

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
```

- [ ] **Step 4: Add member + invite URLs to `monitor/urls.py`**

```python
from monitor.views.settings_views import (
    # ... existing imports ...
    change_member_role, remove_member, invite_member,
    revoke_invite, resend_invite,
)

# in arcwatch/urls.py, accept_invite is already wired via monitor.urls_accounts

# add to monitor/urls.py urlpatterns:
path('settings/members/<int:user_id>/role/', change_member_role, name='change_member_role'),
path('settings/members/<int:user_id>/remove/', remove_member, name='remove_member'),
path('settings/members/invite/', invite_member, name='invite_member'),
path('settings/members/invite/<uuid:token>/revoke/', revoke_invite, name='revoke_invite'),
path('settings/members/invite/<uuid:token>/resend/', resend_invite, name='resend_invite'),
```

- [ ] **Step 5: Build the full `settings_members.html` template**

```html
{% extends "monitor/settings_base.html" %}
{% block settings_content %}
<h2 style="font-family:monospace;color:#e2e8f0;font-size:.95rem;margin:0 0 4px 0">Members</h2>
<p style="color:#64748b;font-size:.72rem;margin:0 0 20px 0">Manage who can access this organization</p>

<!-- Active members -->
<div style="font-size:.65rem;font-family:monospace;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin-bottom:8px">Active Members</div>
<table style="width:100%;border-collapse:collapse;font-size:.78rem;margin-bottom:24px">
  <thead>
    <tr style="border-bottom:1px solid #1e293b">
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">User</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Email</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Role</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Joined</th>
      <th style="padding:8px 10px"></th>
    </tr>
  </thead>
  <tbody>
  {% for member in members %}
    <tr id="member-{{ member.id }}" style="border-bottom:1px solid #1e293b">
      <td style="padding:9px 10px;color:#e2e8f0">{{ member.username }}</td>
      <td style="padding:9px 10px;color:#64748b;font-size:.72rem">{{ member.email }}</td>
      <td style="padding:9px 10px">
        {% if is_admin and member != request.user %}
        <span id="role-{{ member.id }}"
              hx-get="/settings/members/{{ member.id }}/role/"
              style="font-size:.62rem;padding:2px 7px;border-radius:10px;cursor:pointer;
              {% if member.profile.role == 'owner' %}background:rgba(118,185,0,.1);border:1px solid rgba(118,185,0,.25);color:#76B900
              {% elif member.profile.role == 'admin' %}background:rgba(251,191,36,.1);border:1px solid rgba(251,191,36,.25);color:#fbbf24
              {% else %}background:rgba(96,165,250,.1);border:1px solid rgba(96,165,250,.25);color:#60a5fa{% endif %}"
              title="Click to change role">
          {{ member.profile.role }} ▾
        </span>
        {% else %}
        <span style="font-size:.62rem;padding:2px 7px;border-radius:10px;
              {% if member.profile.role == 'owner' %}background:rgba(118,185,0,.1);border:1px solid rgba(118,185,0,.25);color:#76B900
              {% elif member.profile.role == 'admin' %}background:rgba(251,191,36,.1);border:1px solid rgba(251,191,36,.25);color:#fbbf24
              {% else %}background:rgba(96,165,250,.1);border:1px solid rgba(96,165,250,.25);color:#60a5fa{% endif %}">
          {{ member.profile.role }}
        </span>
        {% endif %}
      </td>
      <td style="padding:9px 10px;color:#64748b;font-size:.72rem">{{ member.date_joined|date:"M j, Y" }}</td>
      <td style="padding:9px 10px;text-align:right">
        {% if is_admin and member != request.user %}
        <button hx-post="/settings/members/{{ member.id }}/remove/"
                hx-target="#member-{{ member.id }}"
                hx-swap="outerHTML"
                hx-confirm="Remove {{ member.username }} from this organization?"
                style="background:transparent;border:none;color:#f87171;font-size:.72rem;cursor:pointer;padding:0">Remove</button>
        {% else %}
        <span style="color:#475569;font-size:.72rem">—</span>
        {% endif %}
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="5" style="padding:20px 10px;color:#475569;text-align:center;font-size:.78rem">No members</td></tr>
  {% endfor %}
  </tbody>
</table>

<!-- Pending invites -->
{% if pending_invites %}
<div style="font-size:.65rem;font-family:monospace;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin-bottom:8px">Pending Invites</div>
<table style="width:100%;border-collapse:collapse;font-size:.78rem;margin-bottom:24px">
  <thead>
    <tr style="border-bottom:1px solid #1e293b">
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Email</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Role</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Invited</th>
      <th style="text-align:left;padding:8px 10px;color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.08em">Expires</th>
      <th style="padding:8px 10px"></th>
    </tr>
  </thead>
  <tbody>
  {% for invite in pending_invites %}
    <tr id="invite-{{ invite.token }}" style="border-bottom:1px solid #1e293b">
      <td style="padding:9px 10px;color:#94a3b8;font-size:.75rem">{{ invite.email }}</td>
      <td style="padding:9px 10px">
        <span style="background:rgba(96,165,250,.1);border:1px solid rgba(96,165,250,.25);color:#60a5fa;font-size:.62rem;padding:2px 7px;border-radius:10px">{{ invite.role }}</span>
      </td>
      <td style="padding:9px 10px;color:#64748b;font-size:.72rem">{{ invite.created_at|date:"M j" }}</td>
      <td style="padding:9px 10px;color:#fbbf24;font-size:.72rem">{{ invite.expires_at|date:"M j" }}</td>
      <td style="padding:9px 10px;text-align:right">
        {% if is_admin %}
        <span style="display:inline-flex;gap:10px;font-size:.72rem">
          <button id="resend-{{ invite.token }}"
                  hx-post="/settings/members/invite/{{ invite.token }}/resend/"
                  hx-target="#resend-{{ invite.token }}"
                  hx-swap="outerHTML"
                  style="background:transparent;border:none;color:#60a5fa;cursor:pointer;padding:0">Resend</button>
          <button hx-post="/settings/members/invite/{{ invite.token }}/revoke/"
                  hx-target="#invite-{{ invite.token }}"
                  hx-swap="outerHTML"
                  hx-confirm="Revoke invite for {{ invite.email }}?"
                  style="background:transparent;border:none;color:#f87171;cursor:pointer;padding:0">Revoke</button>
        </span>
        {% endif %}
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}

<!-- Invite form -->
{% if is_admin %}
<div style="background:#111827;border:1px solid #1e293b;border-radius:6px;padding:18px">
  <div style="font-size:.8rem;font-weight:700;color:#e2e8f0;font-family:monospace;margin-bottom:14px">Invite Member</div>
  <form method="post" action="/settings/members/invite/">
    {% csrf_token %}
    <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <div style="flex:1;min-width:200px">
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Email address</label>
        {{ form.email }}
      </div>
      <div style="width:130px">
        <label style="display:block;font-size:.65rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Role</label>
        {{ form.role }}
      </div>
      <button type="submit" style="background:#76B900;color:#000;font-weight:700;font-family:monospace;font-size:.78rem;padding:7px 16px;border:none;border-radius:4px;cursor:pointer">
        Send Invite
      </button>
    </div>
    <div style="margin-top:8px;font-size:.68rem;color:#475569">
      Invite link expires in 7 days · User sets their own password on first login
    </div>
  </form>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Build the full `accept_invite.html` template**

```html
{% extends "monitor/base.html" %}
{% block content %}
<div style="display:flex;align-items:center;justify-content:center;min-height:60vh">
  <div style="width:360px">
    {% if error %}
    <div style="background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.3);color:#f87171;padding:12px 16px;border-radius:6px;font-size:.82rem;text-align:center">
      {{ error }}
    </div>
    {% else %}
    <h2 style="font-family:monospace;color:#e2e8f0;margin-bottom:6px;font-size:1rem">Join {{ invite.organization.name }}</h2>
    <p style="color:#64748b;font-size:.78rem;margin-bottom:20px">
      You've been invited as a <strong style="color:#94a3b8">{{ invite.role }}</strong>. Create your account below.
    </p>
    {% if form.errors %}
    <div style="background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.3);color:#f87171;padding:10px 14px;border-radius:6px;font-size:.78rem;margin-bottom:16px">
      {{ form.non_field_errors }}
      {% for field in form %}{% if field.errors %}{{ field.label }}: {{ field.errors|join:", " }}<br>{% endif %}{% endfor %}
    </div>
    {% endif %}
    <form method="post">
      {% csrf_token %}
      <div style="margin-bottom:12px">
        <label style="display:block;font-size:.72rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Username</label>
        <input name="username" type="text" autofocus value="{{ form.username.value|default:'' }}"
               style="width:100%;background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:8px 12px;border-radius:4px;font-size:.85rem;box-sizing:border-box">
      </div>
      <div style="margin-bottom:12px">
        <label style="display:block;font-size:.72rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Password</label>
        <input name="password" type="password"
               style="width:100%;background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:8px 12px;border-radius:4px;font-size:.85rem;box-sizing:border-box">
      </div>
      <div style="margin-bottom:20px">
        <label style="display:block;font-size:.72rem;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Confirm Password</label>
        <input name="password_confirm" type="password"
               style="width:100%;background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:8px 12px;border-radius:4px;font-size:.85rem;box-sizing:border-box">
      </div>
      <button type="submit"
              style="width:100%;background:#76B900;color:#000;font-weight:700;font-family:monospace;font-size:.88rem;padding:10px;border:none;border-radius:4px;cursor:pointer">
        Create Account &amp; Join
      </button>
    </form>
    {% endif %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Run tests and verify they pass**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py::MembersPageTest -v --keepdb
```

Expected: PASS (4 tests)

- [ ] **Step 8: Run the full test suite to verify nothing regressed**

```bash
USE_SQLITE=1 python -m pytest monitor/tests/test_settings_views.py -v --keepdb
```

Expected: All tests pass.

- [ ] **Step 9: Run the broader test suite**

```bash
USE_SQLITE=1 python -m pytest monitor/ -v --keepdb
```

Expected: All tests pass.

- [ ] **Step 10: Commit**

```bash
git add monitor/views/settings_views.py monitor/urls.py \
        monitor/templates/monitor/settings_members.html \
        monitor/templates/monitor/accept_invite.html
git commit -m "feat: members settings page — role change, remove, email invite flow, accept-invite"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| `@login_required` on all views | Task 1 |
| `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `EMAIL_BACKEND` in settings | Task 1 |
| `django.contrib.auth.urls` wired | Task 1 |
| Login template | Task 1 |
| HTMX CDN + CSRF handler in base.html | Task 4 |
| Settings nav link + user/logout in base.html | Task 4 |
| `is_active` on GPUCluster/GPUNode | Task 2 |
| `Invite` model | Task 2 |
| Migration 0007 | Task 2 |
| `require_admin` decorator | Task 3 |
| Forms (APIKey, AlertRule, Cluster, Endpoint, Invite, AcceptInvite) | Task 3 |
| `settings_base.html` two-column layout + sidebar | Task 4 |
| `/settings/` → redirect to `/settings/api-keys/` | Task 4 |
| API Keys: list, create, revoke (HTMX) | Task 5 |
| Raw key shown once in banner | Task 5 |
| Alert Rules: list, create, edit, toggle (HTMX), delete (HTMX) | Task 6 |
| Resources: cluster create/rename/deactivate/delete | Task 7 |
| Resources: node deactivate/delete | Task 7 |
| Resources: endpoint create/deactivate/delete | Task 7 |
| Resources: two tabs (clusters/endpoints) | Task 7 |
| Members: list, role change (HTMX), remove (HTMX) | Task 8 |
| Pending invites table with Resend/Revoke | Task 8 |
| Invite form: email + role | Task 8 |
| `send_mail` on invite | Task 8 |
| Accept-invite flow: validate token, create user, set profile | Task 8 |
| Expired/accepted token handling | Task 8 |
| HTTP 403 for viewer mutations | Tasks 1, 5, 6, 7, 8 |
| `hx-confirm` on destructive actions | Tasks 6, 7, 8 |
| `HX-Request` header → fragment vs full page | Tasks 5, 6 |
| 404 on missing objects (`get_object_or_404`) | Tasks 5, 6, 7, 8 |
| Test file `monitor/tests/test_settings_views.py` | All tasks |

**No placeholders or TBDs found.**

**Type consistency:** All views use `_get_org(request.user)` and `_is_admin(request.user)` helpers defined at the top of `settings_views.py`. Fragment templates use the same variable names (`rule`, `key`, `invite`) as the views that render them.
