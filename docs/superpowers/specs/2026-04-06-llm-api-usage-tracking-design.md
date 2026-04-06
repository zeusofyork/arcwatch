# LLM API Usage Tracking Design

## Goal

Give ArcWatch organizations real-time visibility into their AI API spend — total monthly cost, per-model breakdown, token usage (including Anthropic cache tokens), request counts, and projected month-end spend — by periodically pulling from provider billing APIs (Anthropic, OpenAI).

## Architecture

Provider API keys are stored encrypted per org. A Celery hourly task syncs the last 32 days of usage from each configured provider into a daily-granularity `LLMUsageRecord` table. A new dashboard page surfaces KPIs, a daily spend chart, and a per-model table. A settings tab lets admins add/remove provider keys and trigger manual syncs.

## Tech Stack

- Django models: `LLMProvider`, `LLMUsageRecord`
- Fernet symmetric encryption (from `cryptography` package, already in requirements) for API key storage
- Celery periodic task (hourly, matching existing beat pattern)
- Provider adapters: `AnthropicAdapter`, `OpenAIAdapter`
- Chart.js (already loaded in `base.html`) for daily spend chart
- HTMX (already loaded) for settings page interactions

---

## Data Models

### `LLMProvider` (`monitor/models/llm.py`)

One row per provider API key configured by an org.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `organization` | FK → Organization | |
| `provider` | CharField choices | `anthropic`, `openai` |
| `label` | CharField(100) | e.g. "Production Key" |
| `api_key_encrypted` | TextField | Fernet-encrypted; never stored plaintext |
| `is_active` | BooleanField | default True |
| `last_synced_at` | DateTimeField null | updated after each successful sync |
| `created_at` | DateTimeField auto | |

### `LLMUsageRecord` (`monitor/models/llm.py`)

One row per (date × provider × model) per org. Upserted on each sync.

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto PK | |
| `date` | DateField | Calendar day (UTC) |
| `organization` | FK → Organization | |
| `provider` | CharField | `anthropic`, `openai` |
| `model` | CharField(200) | e.g. `claude-3-5-sonnet-20241022` |
| `input_tokens` | BigIntegerField | |
| `output_tokens` | BigIntegerField | |
| `cache_creation_tokens` | BigIntegerField | Anthropic only; 0 for others |
| `cache_read_tokens` | BigIntegerField | Anthropic only; 0 for others |
| `request_count` | IntegerField | |
| `cost_usd` | DecimalField(12,6) | Provider-reported cost |

**Unique together**: `(date, organization, provider, model)` — enables idempotent upserts.

---

## Sync Engine (`monitor/services/llm_sync_engine.py`)

### Provider Adapters

Each adapter implements one method:

```python
def fetch(api_key: str, since_date: date, until_date: date) -> list[dict]:
    ...
```

Returns a list of dicts, each with keys matching `LLMUsageRecord` fields (minus `organization`).

**`AnthropicAdapter`**:
- `GET https://api.anthropic.com/v1/usage`
- Params: `start_date=YYYY-MM-DD`, `end_date=YYYY-MM-DD`
- Auth: `x-api-key` header + `anthropic-version: 2023-06-01`
- Response fields used: `model`, `usage_period.start_time` (day), `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `request_count`, `cost`

**`OpenAIAdapter`**:
- Calls `GET https://api.openai.com/v1/usage?date=YYYY-MM-DD` once per day in range
- Auth: `Authorization: Bearer sk-...`
- Response: `data[]` with `snapshot_id` (model), `n_requests`, `n_context_tokens_total`, `n_generated_tokens_total`
- Cost: from `GET https://api.openai.com/v1/dashboard/billing/usage?start_date=...&end_date=...`, matched by day
- `cache_creation_tokens` and `cache_read_tokens` always 0 for OpenAI

### `sync_provider(provider_id: str) -> int`

Core sync function (also called directly for manual sync):

1. Load `LLMProvider` by ID, check `is_active`
2. Decrypt `api_key_encrypted` using Fernet
3. Determine date range: `since = today - 32 days`, `until = today`
4. Call adapter `.fetch(api_key, since, until)`
5. For each returned record: `LLMUsageRecord.objects.update_or_create(date=..., organization=..., provider=..., model=..., defaults={...})`
6. Set `provider.last_synced_at = now()`, save
7. Return count of records written

### `sync_llm_usage()` — Celery task

```python
@shared_task(name="monitor.sync_llm_usage")
def sync_llm_usage() -> int:
    providers = LLMProvider.objects.filter(is_active=True)
    total = 0
    for p in providers:
        try:
            total += sync_provider(str(p.id))
        except Exception as exc:
            logger.warning("LLM sync failed for %s: %s", p.label, exc)
    return total
```

Added to `CELERY_BEAT_SCHEDULE` at 3600s interval.

### Encryption helper

```python
def _get_fernet() -> Fernet:
    # Derive a 32-byte key from Django SECRET_KEY using SHA-256
    import hashlib, base64
    key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))

def encrypt_api_key(raw: str) -> str:
    return _get_fernet().encrypt(raw.encode()).decode()

def decrypt_api_key(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()
```

---

## Settings UI

### New tab: "LLM APIs" in settings sidebar

URL: `/settings/llm-providers/`

Views added to `monitor/views/settings_views.py`:
- `settings_llm_providers(request)` — GET: render list + add form
- `create_llm_provider(request)` — POST: encrypt key, create `LLMProvider`, redirect
- `delete_llm_provider(request, provider_id)` — POST: delete row, return empty (HTMX)
- `toggle_llm_provider(request, provider_id)` — POST: flip `is_active`, return updated badge (HTMX)
- `sync_llm_provider(request, provider_id)` — POST: call `sync_provider()` directly, redirect with `?synced=N` query param

**Add form fields**: provider (dropdown: Anthropic / OpenAI), label (text), api_key (password input).

**Provider list table columns**: label, provider badge, last synced, status toggle (active/inactive), Sync Now button, Delete button.

After manual sync: redirect to `/settings/llm-providers/?synced=<N>` and show a dismissible banner "Synced N records from <label>."

Template: `monitor/templates/monitor/settings_llm_providers.html`

---

## LLM Usage Dashboard

URL: `/llm/`

View: `monitor/views/llm_views.py` → `llm_dashboard(request)` with `@login_required`.

Nav: new sidebar link "LLM APIs" added to `base.html` nav bar.

### Context data computed in view

```python
def _get_llm_summary(org, year, month):
    records = LLMUsageRecord.objects.filter(
        organization=org,
        date__year=year,
        date__month=month,
    )
    # total_cost, total_requests, total_input_tokens, total_output_tokens
    # by_provider: [{provider, cost, requests, pct_of_total}]
    # by_model: [{model, provider, requests, input_tokens, output_tokens,
    #             cache_creation_tokens, cache_read_tokens, cost_usd, cache_hit_rate}]
    # daily_chart: [{date_str, cost_by_provider: {anthropic: x, openai: y}}]
    # projection: cost_so_far / days_elapsed * days_in_month
```

### Dashboard sections

**Header KPIs** (4 cards):
- Total spend this month
- Projected month-end spend (linear extrapolation)
- Total requests this month
- Cache hit rate (Anthropic: `cache_read / (input + cache_read)`, shown as "—" if no Anthropic data)

**By provider** (one card each): cost, request count, % of total spend.

**Daily spend chart**: Chart.js bar chart, last 30 days, stacked by provider (Anthropic green `#76B900`, OpenAI cyan `#00D4AA`).

**By model table**: columns — Model, Provider, Requests, Input Tokens, Output Tokens, Cache Tokens, Cost. Sorted by cost desc. Cache tokens column only shown if any Anthropic data present.

Template: `monitor/templates/monitor/llm_dashboard.html` (extends `base.html`).

---

## Files Created / Modified

**New:**
- `monitor/models/llm.py`
- `monitor/services/llm_sync_engine.py`
- `monitor/views/llm_views.py`
- `monitor/templates/monitor/llm_dashboard.html`
- `monitor/templates/monitor/settings_llm_providers.html`
- `monitor/migrations/000X_llm_models.py`

**Modified:**
- `monitor/models/__init__.py` — export `LLMProvider`, `LLMUsageRecord`
- `monitor/urls.py` — add `/llm/` and `/settings/llm-providers/` routes
- `monitor/views/settings_views.py` — add LLM provider views (create, delete, toggle, sync)
- `monitor/templates/monitor/base.html` — add "LLM APIs" nav link
- `arcwatch/settings.py` — add `sync-llm-usage` to `CELERY_BEAT_SCHEDULE`

---

## Error Handling

- Adapter HTTP errors (4xx/5xx): log warning, increment error counter, do not raise — other providers continue syncing
- Decryption failure: log error, skip provider
- Unknown provider type: log warning, skip
- Manual sync errors: surface error message on redirect (`?error=...` query param)

## Testing

- `LLMProvider` encrypt/decrypt round-trip
- `AnthropicAdapter.fetch()` with mocked HTTP response → correct record shape
- `OpenAIAdapter.fetch()` with mocked HTTP response → correct record shape
- `sync_provider()`: writes correct `LLMUsageRecord` rows, updates `last_synced_at`
- Upsert idempotency: calling `sync_provider()` twice produces same row count (no duplicates)
- Dashboard view: returns 200 with correct KPI values from test data
- Projection calculation: correct linear extrapolation
- Settings views: add/delete/sync provider, RBAC (viewer gets 403 on create/delete/sync)
