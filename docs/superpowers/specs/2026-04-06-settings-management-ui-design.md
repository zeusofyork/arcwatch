# ArcWatch Settings Management UI — Design Spec

**Date:** 2026-04-06
**Status:** Approved

---

## Overview

Add a `/settings/` section to ArcWatch with four management pages: API Keys, Alert Rules, Resources, and Members. All pages — including existing dashboards — require Django login. Access is role-gated: readers can view, admins can modify.

---

## Auth & RBAC

### Login requirement
Every view (dashboards + settings) is protected by Django's `@login_required` decorator (or `LoginRequiredMixin`). Unauthenticated requests redirect to `/accounts/login/`.

Django's built-in auth views are wired at `path('accounts/', include('django.contrib.auth.urls'))` in `arcwatch/urls.py`. `LOGIN_URL` and `LOGIN_REDIRECT_URL` are set in `arcwatch/settings.py`.

### Role model
The existing `UserProfile.role` field (`viewer`, `operator`, `admin`, `owner`) is used as-is.

| Role | Access |
|------|--------|
| `viewer`, `operator` | Read-only: can view all dashboards and all settings pages |
| `admin`, `owner` | Full access: can create, edit, delete on all settings pages |

A reusable `require_admin` decorator checks `request.user.profile.role in ('admin', 'owner')` and returns HTTP 403 on violation. Read-only views use only `@login_required`. Mutating views use both.

---

## Navigation

`base.html` gains:
- A **⚙ Settings** link in the top nav (far right, before the user avatar)
- A **👤 username + logout** display in the top nav (replaces the LIVE indicator's right side)

The Settings link is visible to all logged-in users. Mutating controls within settings pages are hidden (via `{% if is_admin %}`) for viewer/operator roles.

---

## Settings Structure

```
/settings/                      → redirect to /settings/api-keys/
/settings/api-keys/             → list + create API keys
/settings/api-keys/<id>/revoke/ → POST: revoke key (HTMX)
/settings/alert-rules/          → list + create/edit/delete rules
/settings/alert-rules/create/   → POST: create rule
/settings/alert-rules/<id>/edit/    → GET+POST: edit rule form
/settings/alert-rules/<id>/toggle/  → POST: toggle is_enabled (HTMX)
/settings/alert-rules/<id>/delete/  → POST: delete rule (HTMX)
/settings/resources/            → Clusters & Nodes tab + Inference Endpoints tab
/settings/resources/clusters/create/          → POST
/settings/resources/clusters/<id>/rename/     → POST (HTMX)
/settings/resources/clusters/<id>/deactivate/ → POST (HTMX)
/settings/resources/clusters/<id>/delete/     → POST (HTMX)
/settings/resources/nodes/<id>/deactivate/    → POST (HTMX)
/settings/resources/nodes/<id>/delete/        → POST (HTMX)
/settings/resources/endpoints/create/         → POST
/settings/resources/endpoints/<id>/rename/    → POST (HTMX)
/settings/resources/endpoints/<id>/deactivate/→ POST (HTMX)
/settings/resources/endpoints/<id>/delete/    → POST (HTMX)
/settings/members/              → list members + pending invites + invite form
/settings/members/<id>/role/    → POST: change role (HTMX)
/settings/members/<id>/remove/  → POST: remove member (HTMX)
/settings/members/invite/       → POST: send invite email
/settings/members/invite/<token>/revoke/ → POST (HTMX)
/settings/members/invite/<token>/resend/ → POST (HTMX)
/accounts/accept-invite/<token>/→ GET+POST: accept invite, set password, join org
```

---

## Components

### Settings layout (`settings_base.html`)
Extends `base.html`. Provides a two-column layout: fixed left sidebar (180 px) + scrollable content area. Sidebar links: API Keys · Alert Rules · Resources · Members. Active link highlighted with green left border. All settings templates extend `settings_base.html`.

### API Keys page
- Lists all `APIKey` rows for the org: name, 8-char prefix, scopes badge, last used, active/revoked status.
- **Create**: a form (name + scopes checkboxes) POSTs to the same page. On success, the raw key is displayed once in a dismissable `⚠ Copy now` banner, then the page reloads.
- **Revoke**: HTMX `hx-post` on the Revoke button. The view sets `active=False` and returns a replacement row fragment showing "revoked" status. No confirmation dialog — the row stays visible (dimmed) so the name and prefix are still readable.

### Alert Rules page
- Lists all `AlertRule` rows: name, metric (display label), threshold, Slack webhook set/not-set, enabled toggle, Edit/Delete actions.
- **Toggle enabled**: HTMX `hx-post` on the ON/OFF badge. Returns a replacement badge fragment only.
- **Create/Edit**: inline form panel below the table (hidden by default, revealed by "+ New Rule" or "Edit" click via `hx-get` loading the form fragment). Fields: name, metric (select), threshold (number), duration_seconds (number, default 300), slack_webhook_url (optional).
- **Delete**: HTMX `hx-post` with `hx-confirm` dialog. Returns an empty string (HTMX removes the row via `hx-swap="outerHTML"`).

### Resources page
Two tabs (Clusters & Nodes / Inference Endpoints) implemented as plain anchor links with `?tab=` query param — no JS required.

**Clusters & Nodes tab:**
- Clusters listed as expandable cards. Each card shows cluster name, node count, GPU count.
- Nodes listed inline under their cluster with current status badge.
- Cluster actions: Rename (inline HTMX text edit), Deactivate (sets `GPUCluster.is_active=False`, HTMX swaps badge), Delete (hard delete, HTMX removes card — only allowed if no active nodes).
- Node actions: Deactivate (sets `GPUNode.is_active=False`), Delete (hard delete, HTMX removes row).
- **Note:** `GPUCluster` and `GPUNode` both need an `is_active = BooleanField(default=True)` added in migration `0007`. `InferenceEndpoint` already has this field.
- **Add Cluster**: form with name field. On POST, page reloads showing the new cluster card.

**Inference Endpoints tab:**
- Lists `InferenceEndpoint` rows: name, engine, status, last seen.
- Actions: Rename (HTMX inline), Deactivate (sets `status='retired'`), Delete (hard delete).
- **Add Endpoint**: form with name, engine (select), url fields.

**Deactivate vs Delete:** Deactivated resources keep their DB rows and history (cost snapshots, alert events still reference them) but are excluded from dashboard queries via an `is_active=False` filter. Hard delete cascades and removes all related rows — requires a second confirmation (`hx-confirm`).

### Members page
Three sections:

**Active Members table:** username, email, role badge (clickable for admins → HTMX inline `<select>` swap), joined date, Remove button (HTMX, with `hx-confirm`). The current user's own row shows `—` in the action column (cannot self-remove).

**Pending Invites table:** email, role, invited timestamp, expiry countdown, Resend + Revoke actions (both HTMX).

**Invite form:** email address + role select (viewer / admin / owner) + Send Invite button. On POST, creates an `Invite` DB row and sends an email via Django's `send_mail`. The invite link is `/accounts/accept-invite/<uuid-token>/` and expires after 7 days.

---

## Invite Flow

### New model: `Invite`
```
organization  FK → Organization
invited_by    FK → User
email         EmailField
role          CharField (viewer/admin/owner)
token         UUIDField (primary key, default=uuid4)
created_at    DateTimeField (auto_now_add)
expires_at    DateTimeField  (created_at + 7 days)
accepted_at   DateTimeField (null → pending)
```

### Accept flow
`GET /accounts/accept-invite/<token>/` — validates token exists, not expired, not already accepted. Renders a form with username + password fields.
`POST /accounts/accept-invite/<token>/` — creates a Django `User`, sets their `UserProfile.organization` and `UserProfile.role`, marks invite `accepted_at=now()`, logs them in, redirects to `/`.

If token is expired: show "This invite has expired. Ask an admin to resend it."
If already accepted: redirect to login.

### Email
Uses Django's `send_mail`. In development `EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'` (prints to stdout). In production, configure `EMAIL_BACKEND`, `EMAIL_HOST`, etc. via environment variables.

---

## New Files

| Action | Path |
|--------|------|
| Create | `monitor/views/settings_views.py` |
| Create | `monitor/forms.py` |
| Create | `monitor/templates/monitor/settings_base.html` |
| Create | `monitor/templates/monitor/settings_api_keys.html` |
| Create | `monitor/templates/monitor/settings_alert_rules.html` |
| Create | `monitor/templates/monitor/settings_resources.html` |
| Create | `monitor/templates/monitor/settings_members.html` |
| Create | `monitor/templates/monitor/accept_invite.html` |
| Create | `monitor/migrations/0007_invite.py` |
| Modify | `monitor/models/__init__.py` — export `Invite` |
| Modify | `monitor/models/organization.py` — add `Invite` model |
| Modify | `monitor/urls.py` — add settings + accept-invite URLs |
| Modify | `arcwatch/urls.py` — add `django.contrib.auth.urls` |
| Modify | `arcwatch/settings.py` — add `LOGIN_URL`, `LOGIN_REDIRECT_URL`, email backend |
| Modify | `monitor/templates/monitor/base.html` — add Settings nav link + user/logout display |
| Modify | `monitor/views/dashboard_views.py` — add `@login_required` |
| Modify | `monitor/views/inference_views.py` — add `@login_required` |
| Modify | `monitor/views/cost_views.py` — add `@login_required` |
| Modify | `monitor/views/alert_views.py` — add `@login_required` |

---

## HTMX

HTMX is loaded from CDN in `base.html` (`https://unpkg.com/htmx.org@1.9.12`). No other HTMX configuration is needed. All HTMX endpoints return HTML fragments (a single `<tr>`, a badge `<span>`, or an empty string for delete). They share the same view functions as the full-page views, switching on `HX-Request` header to return fragment vs. full page.

---

## Error Handling

- **403 on role violation**: `require_admin` returns a plain 403 response with a short message ("Admin access required").
- **404 on missing objects**: all settings views use `get_object_or_404`.
- **Form validation errors**: re-render the inline form fragment with error messages below each field.
- **HTMX errors**: if a non-2xx response is returned, HTMX leaves the DOM unchanged. A global `htmx:responseError` event listener (added to `base.html`) shows a small toast notification.

---

## Testing

- `monitor/tests/test_settings_views.py` — covers all settings views
- Auth: unauthenticated → 302 redirect; viewer → 200 on GET, 403 on POST mutation; admin → 200/302 on all
- API keys: create returns raw key in context, revoke sets `active=False`
- Alert rules: create/edit/delete/toggle all validated
- Resources: deactivate sets correct status field, delete cascades
- Members: invite creates `Invite` row and calls `send_mail` (mocked), accept flow creates `User` + `UserProfile`

---

## Out of Scope

- Two-factor authentication
- OAuth / SSO
- Billing / plan management
- Audit log UI (events are already in `AlertEvent` but no dedicated UI)
- Email template styling (plain text emails only)
