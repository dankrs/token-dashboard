import os
import tempfile
import unittest
from datetime import datetime

from token_dashboard.db import init_db, connect
from token_dashboard.pricing import load_pricing, set_budget
from token_dashboard.trends import cost_daily, trends_summary, cost_drivers

PRICING = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pricing.json"))
MOD = "-5 hours"  # deterministic stand-in for CDT localtime


def _ins(c, uuid, ts, model="claude-opus-4-7", inp=1_000_000, out=0):
    c.execute(
        "INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens) "
        "VALUES (?, 's','p','assistant', ?, ?, ?, ?)", (uuid, ts, model, inp, out))


class CostDailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.db = os.path.join(self.tmp, "t.db"); init_db(self.db)
        self.p = load_pricing(PRICING)
        with connect(self.db) as c:
            _ins(c, "a", "2026-05-12T20:00:00Z", inp=1_000_000)  # opus input -> $5
            _ins(c, "b", "2026-05-12T21:00:00Z", inp=1_000_000)  # +$5 same local day
            _ins(c, "c", "2026-05-13T20:00:00Z", inp=1_000_000)  # $5 next day
            c.commit()

    def test_cost_daily_groups_and_costs(self):
        series = cost_daily(self.db, self.p, day_modifier=MOD)
        days = {d["day"]: d["cost_usd"] for d in series}
        self.assertAlmostEqual(days["2026-05-12"], 10.00, places=4)
        self.assertAlmostEqual(days["2026-05-13"], 5.00, places=4)


class TrendsSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.db = os.path.join(self.tmp, "t.db"); init_db(self.db)
        self.p = load_pricing(PRICING)
        # "now" pinned to 2026-05-21 12:00 local
        self.now = datetime(2026, 5, 21, 12, 0, 0)
        with connect(self.db) as c:
            _ins(c, "tm", "2026-05-20T20:00:00Z", inp=1_000_000)   # this month + this week ($5)
            _ins(c, "lw", "2026-05-10T20:00:00Z", inp=2_000_000)   # this month, last week ($10)
            _ins(c, "lm", "2026-04-15T20:00:00Z", inp=4_000_000)   # last month ($20)
            c.commit()

    def test_period_totals(self):
        s = trends_summary(self.db, self.p, now=self.now, day_modifier=MOD)
        self.assertAlmostEqual(s["periods"]["this_month"]["cost_usd"], 15.00, places=4)  # 5+10
        self.assertAlmostEqual(s["periods"]["last_month"]["cost_usd"], 20.00, places=4)
        self.assertAlmostEqual(s["periods"]["this_week"]["cost_usd"], 5.00, places=4)   # only 05-20
        self.assertAlmostEqual(s["periods"]["last_week"]["cost_usd"], 10.00, places=4)  # 05-10

    def test_mom_delta_sign(self):
        s = trends_summary(self.db, self.p, now=self.now, day_modifier=MOD)
        # this_month 15 vs last_month 20 -> -0.25
        self.assertAlmostEqual(s["periods"]["this_month"]["delta_pct"], -0.25, places=4)

    def test_budget_status_unset(self):
        s = trends_summary(self.db, self.p, now=self.now, day_modifier=MOD)
        self.assertEqual(s["budget"]["status"], "unset")
        self.assertIsNone(s["budget"]["monthly_usd"])
        self.assertAlmostEqual(s["budget"]["spent_this_month_usd"], 15.00, places=4)

    def test_budget_status_thresholds(self):
        set_budget(self.db, 15)            # spent 15 / 15 = 100% -> over
        s = trends_summary(self.db, self.p, now=self.now, day_modifier=MOD)
        self.assertEqual(s["budget"]["status"], "over")
        set_budget(self.db, 18)            # 15/18 = 83% -> warn
        s = trends_summary(self.db, self.p, now=self.now, day_modifier=MOD)
        self.assertEqual(s["budget"]["status"], "warn")
        set_budget(self.db, 100)           # 15/100 = 15% -> ok
        s = trends_summary(self.db, self.p, now=self.now, day_modifier=MOD)
        self.assertEqual(s["budget"]["status"], "ok")


class CostDriversTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.db = os.path.join(self.tmp, "t.db"); init_db(self.db)
        self.p = load_pricing(PRICING)
        with connect(self.db) as c:
            # opus: 1M input ($5) + 1M output ($25) in projA  (explicit project_slug)
            c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens) "
                      "VALUES ('a','s','projA','assistant','2026-05-11T12:00:00Z','claude-opus-4-7',1000000,1000000)")
            # sonnet: 1M output ($15) in projB
            c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, output_tokens) "
                      "VALUES ('b','s','projB','assistant','2026-05-11T12:00:00Z','claude-sonnet-4-6',1000000)")
            c.commit()

    def test_total_and_by_type(self):
        d = cost_drivers(self.db, self.p)
        self.assertAlmostEqual(d["total_usd"], 45.00, places=4)  # 5+25+15
        bt = {x["type"]: x["cost_usd"] for x in d["by_type"]}
        self.assertAlmostEqual(bt["output"], 40.00, places=4)  # 25 opus + 15 sonnet
        self.assertAlmostEqual(bt["input"], 5.00, places=4)

    def test_by_model_and_project_sorted(self):
        d = cost_drivers(self.db, self.p)
        self.assertEqual(d["by_model"][0]["model"], "claude-opus-4-7")  # $30 > $15
        self.assertAlmostEqual(d["by_model"][0]["cost_usd"], 30.00, places=4)
        self.assertEqual(d["by_project"][0]["project_slug"], "projA")   # $30 > $15
        self.assertAlmostEqual(d["by_project"][0]["pct"], 30.0 / 45.0, places=3)

    def test_empty_window(self):
        empty_db = os.path.join(self.tmp, "e.db"); init_db(empty_db)
        d = cost_drivers(empty_db, self.p)
        self.assertEqual(d["total_usd"], 0.0)
        self.assertEqual(d["by_type"], [])
        self.assertEqual(d["by_model"], [])
        self.assertEqual(d["by_project"], [])


if __name__ == "__main__":
    unittest.main()
