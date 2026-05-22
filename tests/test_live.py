import os
import tempfile
import unittest
from datetime import datetime

from token_dashboard.db import init_db, connect
from token_dashboard.pricing import load_pricing
from token_dashboard.live import live_summary

PRICING = load_pricing(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pricing.json")))
MOD = "-5 hours"  # deterministic stand-in for CDT localtime


def _ins(c, uuid, sid, ts, mtype="assistant", model="claude-opus-4-7", inp=0, out=0, project="p", cwd="/home/u/proj"):
    c.execute(
        "INSERT INTO messages (uuid, session_id, project_slug, cwd, type, timestamp, model, input_tokens, output_tokens) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (uuid, sid, project, cwd, mtype, ts, model, inp, out))


class ActiveSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.db = os.path.join(self.tmp, "t.db"); init_db(self.db)

    def test_empty_db(self):
        s = live_summary(self.db, PRICING, now=datetime(2026, 5, 21, 21, 0, 0), day_modifier=MOD)
        self.assertIsNone(s["active"])
        self.assertEqual(s["today"], {"cost_usd": 0.0, "tokens": 0, "sessions": 0, "turns": 0})

    def test_picks_most_recent_session_and_costs(self):
        with connect(self.db) as c:
            _ins(c, "old", "s_old", "2026-05-20T18:00:00Z", inp=1_000_000)
            _ins(c, "u", "s_new", "2026-05-21T20:00:00Z", mtype="user", model=None)
            _ins(c, "a1", "s_new", "2026-05-21T20:00:01Z", inp=1_000_000)  # $5
            _ins(c, "a2", "s_new", "2026-05-21T21:00:01Z", inp=0)          # +1h elapsed
            c.commit()
        s = live_summary(self.db, PRICING, now=datetime(2026, 5, 21, 21, 0, 31), day_modifier=MOD)
        a = s["active"]
        self.assertEqual(a["session_id"], "s_new")
        self.assertAlmostEqual(a["cost_usd"], 5.00, places=4)
        self.assertEqual(a["turns"], 1)
        self.assertEqual(a["model"], "claude-opus-4-7")

    def test_burn_rate_and_active_flag(self):
        with connect(self.db) as c:
            _ins(c, "a1", "s", "2026-05-21T20:00:01Z", inp=1_000_000)  # $5
            _ins(c, "a2", "s", "2026-05-21T21:00:01Z", inp=0)          # elapsed 3600s
            c.commit()
        s = live_summary(self.db, PRICING, now=datetime(2026, 5, 21, 21, 0, 31), day_modifier=MOD)
        a = s["active"]
        self.assertAlmostEqual(a["elapsed_seconds"], 3600, delta=1)
        self.assertAlmostEqual(a["burn_usd_per_hr"], 5.00, places=2)  # $5 over 1h
        self.assertTrue(a["is_active"])  # age 30s < 600

    def test_idle_when_old(self):
        with connect(self.db) as c:
            _ins(c, "a1", "s", "2026-05-21T20:00:00Z", inp=1_000_000)
            _ins(c, "a2", "s", "2026-05-21T21:00:00Z", inp=0)
            c.commit()
        s = live_summary(self.db, PRICING, now=datetime(2026, 5, 21, 21, 30, 0), day_modifier=MOD)  # age 1800s
        self.assertFalse(s["active"]["is_active"])

    def test_burn_none_under_floor(self):
        with connect(self.db) as c:
            _ins(c, "a1", "s", "2026-05-21T20:00:00Z", inp=1_000_000)
            _ins(c, "a2", "s", "2026-05-21T20:00:30Z", inp=0)  # elapsed 30s < 120
            c.commit()
        s = live_summary(self.db, PRICING, now=datetime(2026, 5, 21, 20, 1, 0), day_modifier=MOD)
        self.assertIsNone(s["active"]["burn_usd_per_hr"])


class TodayTotalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.db = os.path.join(self.tmp, "t.db"); init_db(self.db)

    def test_today_buckets_by_local_day(self):
        with connect(self.db) as c:
            # 02:00Z -> local (UTC-5) 2026-05-20 -> NOT today
            _ins(c, "x", "s1", "2026-05-21T02:00:00Z", inp=1_000_000)
            # 20:00Z -> local 2026-05-21 -> today
            _ins(c, "y", "s2", "2026-05-21T20:00:00Z", inp=2_000_000)  # $10
            _ins(c, "yu", "s2", "2026-05-21T20:00:01Z", mtype="user", model=None)
            c.commit()
        s = live_summary(self.db, PRICING, now=datetime(2026, 5, 21, 21, 0, 0), day_modifier=MOD)
        self.assertAlmostEqual(s["today"]["cost_usd"], 10.00, places=4)
        self.assertEqual(s["today"]["sessions"], 1)   # only s2 is today
        self.assertEqual(s["today"]["turns"], 1)


if __name__ == "__main__":
    unittest.main()
