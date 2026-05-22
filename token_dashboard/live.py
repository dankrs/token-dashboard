"""Live current-session + today-so-far summary for the Live tab."""
from __future__ import annotations

from datetime import datetime, timezone

from .db import connect, best_project_name
from .pricing import total_cost

_BURN_FLOOR_S = 120  # below this, $/hr is too noisy to report

_MODEL_COLS = """
  COALESCE(model,'unknown') AS model,
  COALESCE(SUM(input_tokens),0)            AS input_tokens,
  COALESCE(SUM(output_tokens),0)           AS output_tokens,
  COALESCE(SUM(cache_read_tokens),0)       AS cache_read_tokens,
  COALESCE(SUM(cache_create_5m_tokens),0)  AS cache_create_5m_tokens,
  COALESCE(SUM(cache_create_1h_tokens),0)  AS cache_create_1h_tokens
"""

_BILLABLE = "input_tokens+output_tokens+cache_create_5m_tokens+cache_create_1h_tokens"


def _utc_iso(now) -> str:
    """ISO string in UTC for SQLite julianday/strftime. Naive `now` is treated as UTC."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is not None:
        now = now.astimezone(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _billable(row) -> int:
    return (row["input_tokens"] + row["output_tokens"]
            + row["cache_create_5m_tokens"] + row["cache_create_1h_tokens"])


def _active(c, pricing, now_iso, threshold_s):
    head = c.execute("SELECT session_id, MAX(timestamp) AS last FROM messages").fetchone()
    if not head or not head["last"]:
        return None
    sid = head["session_id"]
    meta = c.execute(f"""
      SELECT project_slug,
             MIN(timestamp) AS started, MAX(timestamp) AS last_activity,
             SUM(CASE WHEN type='user' THEN 1 ELSE 0 END) AS turns,
             COALESCE(SUM({_BILLABLE}),0) AS tokens,
             (julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 86400 AS elapsed_s
        FROM messages WHERE session_id=?
    """, (sid,)).fetchone()
    age_s = c.execute(
        "SELECT (julianday(?) - julianday(?)) * 86400", (now_iso, meta["last_activity"])
    ).fetchone()[0] or 0.0
    model_rows = c.execute(
        f"SELECT {_MODEL_COLS} FROM messages WHERE session_id=? AND type='assistant' GROUP BY model",
        (sid,),
    ).fetchall()
    cost = total_cost(model_rows, pricing)
    model, best = None, -1
    for r in model_rows:
        bt = _billable(r)
        if bt > best:
            best, model = bt, r["model"]
    cwds = [x["cwd"] for x in c.execute(
        "SELECT DISTINCT cwd FROM messages WHERE session_id=? AND cwd IS NOT NULL", (sid,))]
    elapsed_s = meta["elapsed_s"] or 0.0
    burn = round(cost / (elapsed_s / 3600), 4) if elapsed_s >= _BURN_FLOOR_S else None
    return {
        "session_id": sid,
        "project_name": best_project_name(cwds, meta["project_slug"]),
        "project_slug": meta["project_slug"],
        "model": model,
        "started": meta["started"],
        "last_activity": meta["last_activity"],
        "age_seconds": round(age_s, 1),
        "is_active": age_s < threshold_s,
        "turns": meta["turns"] or 0,
        "tokens": meta["tokens"] or 0,
        "cost_usd": cost,
        "elapsed_seconds": round(elapsed_s, 1),
        "burn_usd_per_hr": burn,
    }


def _today(c, pricing, day_modifier, today):
    model_rows = c.execute(
        f"SELECT {_MODEL_COLS} FROM messages "
        f"WHERE type='assistant' AND strftime('%Y-%m-%d', timestamp, ?)=? GROUP BY model",
        (day_modifier, today),
    ).fetchall()
    meta = c.execute(
        f"SELECT COUNT(DISTINCT session_id) AS sessions, "
        f"SUM(CASE WHEN type='user' THEN 1 ELSE 0 END) AS turns, "
        f"COALESCE(SUM({_BILLABLE}),0) AS tokens "
        f"FROM messages WHERE strftime('%Y-%m-%d', timestamp, ?)=?",
        (day_modifier, today),
    ).fetchone()
    return {
        "cost_usd": total_cost(model_rows, pricing),
        "tokens": meta["tokens"] or 0,
        "sessions": meta["sessions"] or 0,
        "turns": meta["turns"] or 0,
    }


def live_summary(db_path, pricing, now=None, day_modifier="localtime", active_threshold_s=600):
    """Active-session card data + today-so-far totals. See spec for the shape.

    `now` is a UTC instant (naive treated as UTC); it drives both age_seconds and the
    local 'today' date (derived in SQL with the same `day_modifier` as row bucketing).
    """
    now_iso = _utc_iso(now)
    with connect(db_path) as c:
        today = c.execute("SELECT strftime('%Y-%m-%d', ?, ?)", (now_iso, day_modifier)).fetchone()[0]
        return {
            "active": _active(c, pricing, now_iso, active_threshold_s),
            "today": _today(c, pricing, day_modifier, today),
        }
