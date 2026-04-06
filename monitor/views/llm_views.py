"""monitor/views/llm_views.py — LLM API usage dashboard."""
import calendar
import datetime
import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from monitor.models import LLMUsageRecord


def _get_org(user):
    try:
        profile = user.profile
        return profile.organization
    except AttributeError:
        return None


@login_required
def llm_dashboard(request):
    org = _get_org(request.user)
    today = datetime.date.today()
    year, month = today.year, today.month
    days_in_month = calendar.monthrange(year, month)[1]
    days_elapsed = max(today.day, 1)

    records = list(
        LLMUsageRecord.objects.filter(
            organization=org,
            date__year=year,
            date__month=month,
        )
    ) if org else []

    # ── Totals ────────────────────────────────────────────────────────────────
    total_cost = sum(float(r.cost_usd) for r in records)
    total_requests = sum(r.request_count for r in records)

    projection = round(total_cost / days_elapsed * days_in_month, 4) if total_cost else 0

    # Cache hit rate (Anthropic only)
    anthr_records = [r for r in records if r.provider == "anthropic"]
    cache_hit_rate = None
    if anthr_records:
        anthr_input = sum(r.input_tokens for r in anthr_records)
        anthr_cache_read = sum(r.cache_read_tokens for r in anthr_records)
        denominator = anthr_input + anthr_cache_read
        cache_hit_rate = round(anthr_cache_read / denominator * 100, 1) if denominator else 0.0

    # ── By provider ───────────────────────────────────────────────────────────
    provider_totals: dict = {}
    for r in records:
        if r.provider not in provider_totals:
            provider_totals[r.provider] = {"cost": 0.0, "requests": 0}
        provider_totals[r.provider]["cost"] += float(r.cost_usd)
        provider_totals[r.provider]["requests"] += r.request_count

    by_provider = [
        {
            "provider": p,
            "cost": round(d["cost"], 4),
            "requests": d["requests"],
            "pct": round(d["cost"] / total_cost * 100, 1) if total_cost else 0,
        }
        for p, d in sorted(provider_totals.items(), key=lambda x: -x[1]["cost"])
    ]

    # ── By model ──────────────────────────────────────────────────────────────
    model_totals: dict = {}
    for r in records:
        key = (r.provider, r.model)
        if key not in model_totals:
            model_totals[key] = {
                "provider": r.provider, "model": r.model,
                "requests": 0, "input_tokens": 0, "output_tokens": 0,
                "cache_creation_tokens": 0, "cache_read_tokens": 0, "cost": 0.0,
            }
        d = model_totals[key]
        d["requests"] += r.request_count
        d["input_tokens"] += r.input_tokens
        d["output_tokens"] += r.output_tokens
        d["cache_creation_tokens"] += r.cache_creation_tokens
        d["cache_read_tokens"] += r.cache_read_tokens
        d["cost"] += float(r.cost_usd)

    by_model = sorted(model_totals.values(), key=lambda x: -x["cost"])
    for m in by_model:
        m["cost"] = round(m["cost"], 4)
        denominator = m["input_tokens"] + m["cache_read_tokens"]
        m["cache_hit_rate"] = (
            round(m["cache_read_tokens"] / denominator * 100, 1) if denominator else None
        )

    has_anthropic = any(m["provider"] == "anthropic" for m in by_model)

    # ── Daily chart (last 30 days) ────────────────────────────────────────────
    since_30 = today - datetime.timedelta(days=29)
    daily_records = list(
        LLMUsageRecord.objects.filter(
            organization=org,
            date__gte=since_30,
        )
    ) if org else []

    day_map: dict = {}
    for r in daily_records:
        ds = r.date.isoformat()
        if ds not in day_map:
            day_map[ds] = {"anthropic": 0.0, "openai": 0.0}
        day_map[ds][r.provider] = day_map[ds].get(r.provider, 0.0) + float(r.cost_usd)

    chart_labels = []
    chart_anthropic = []
    chart_openai = []
    d = since_30
    while d <= today:
        ds = d.isoformat()
        chart_labels.append(d.strftime("%b %d"))
        vals = day_map.get(ds, {})
        chart_anthropic.append(round(vals.get("anthropic", 0.0), 4))
        chart_openai.append(round(vals.get("openai", 0.0), 4))
        d += datetime.timedelta(days=1)

    return render(request, "monitor/llm_dashboard.html", {
        "total_cost": round(total_cost, 4),
        "total_requests": total_requests,
        "projection": projection,
        "cache_hit_rate": cache_hit_rate,
        "by_provider": by_provider,
        "by_model": by_model,
        "has_anthropic": has_anthropic,
        "chart_labels": json.dumps(chart_labels),
        "chart_anthropic": json.dumps(chart_anthropic),
        "chart_openai": json.dumps(chart_openai),
        "month_name": today.strftime("%B %Y"),
    })
