"""Cost-over-time series + calendar period/budget summary for the Trends tab."""
from __future__ import annotations

from datetime import datetime, date, timedelta

from .db import daily_model_breakdown
from .pricing import cost_for, get_budget


def cost_daily(db_path, pricing, since=None, until=None, day_modifier="localtime"):
    """[{day, cost_usd}] in local days, ascending. Only days with activity."""
    by_day = {}
    for r in daily_model_breakdown(db_path, since, until, day_modifier=day_modifier):
        c = cost_for(r["model"], r, pricing)
        if c["usd"] is not None:
            by_day[r["day"]] = by_day.get(r["day"], 0.0) + c["usd"]
    return [{"day": d, "cost_usd": round(v, 6)} for d, v in sorted(by_day.items())]


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _next_month(first: date) -> date:
    return first.replace(year=first.year + 1, month=1) if first.month == 12 \
        else first.replace(month=first.month + 1)


def trends_summary(db_path, pricing, now=None, day_modifier="localtime"):
    """Calendar-fixed KPIs: budget status + this/last month and week totals.

    `now` defaults to local datetime.now(); injectable for tests. Period boundaries
    are local dates; day buckets are local (matching `day_modifier`).
    """
    now = now or datetime.now()
    today = now.date()

    this_month_start = _month_start(today)
    next_month_start = _next_month(this_month_start)
    last_month_start = _month_start(this_month_start - timedelta(days=1))

    # Fetch a window wide enough to cover last month + the two trailing weeks, padded
    # one day each side so UTC/local boundary rows are never truncated.
    window_start = min(last_month_start, today - timedelta(days=13)) - timedelta(days=1)
    window_end = today + timedelta(days=2)
    daily = cost_daily(db_path, pricing,
                       since=window_start.isoformat(), until=window_end.isoformat(),
                       day_modifier=day_modifier)
    by_day = {d["day"]: d["cost_usd"] for d in daily}

    def total(start: date, end: date) -> float:  # [start, end)
        s, d = 0.0, start
        while d < end:
            s += by_day.get(d.isoformat(), 0.0)
            d += timedelta(days=1)
        return round(s, 6)

    def delta(cur: float, prior: float):
        return round((cur - prior) / prior, 4) if prior else None

    this_month = total(this_month_start, next_month_start)
    last_month = total(last_month_start, this_month_start)
    this_week = total(today - timedelta(days=6), today + timedelta(days=1))
    last_week = total(today - timedelta(days=13), today - timedelta(days=6))

    monthly = get_budget(db_path)
    if monthly and monthly > 0:
        pct = round(this_month / monthly, 4)
        status = "over" if pct >= 1.0 else ("warn" if pct >= 0.8 else "ok")
    else:
        monthly, pct, status = None, None, "unset"

    return {
        "budget": {
            "monthly_usd": monthly,
            "spent_this_month_usd": this_month,
            "pct": pct,
            "status": status,
        },
        "periods": {
            "this_month": {"cost_usd": this_month, "delta_pct": delta(this_month, last_month)},
            "last_month": {"cost_usd": last_month, "delta_pct": None},
            "this_week":  {"cost_usd": this_week,  "delta_pct": delta(this_week, last_week)},
            "last_week":  {"cost_usd": last_week,  "delta_pct": None},
        },
    }
