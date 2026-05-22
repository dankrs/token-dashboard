import os
import tempfile
import unittest

from token_dashboard.db import init_db, connect
from token_dashboard.pricing import load_pricing, set_budget
from token_dashboard.tips import (
    cache_discipline_tips, repeated_target_tips, right_size_tips,
    outlier_tips, all_tips, dismiss_tip, budget_tips,
    project_concentration_tips, expensive_prompt_tips,
    cache_rebuild_cost_tips, output_heavy_tips,
)

_PRICING = load_pricing(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pricing.json")))


class CacheTipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        init_db(self.db)

    def _ins(self, ts, project, cache_read, cache_create):
        with connect(self.db) as c:
            c.execute("""INSERT INTO messages (uuid, session_id, project_slug, type, timestamp,
                model, input_tokens, output_tokens, cache_read_tokens,
                cache_create_5m_tokens, cache_create_1h_tokens) VALUES
                (?, 's', ?, 'assistant', ?, 'claude-opus-4-7', 100, 100, ?, ?, 0)""",
                (f"uuid-{ts}", project, ts, cache_read, cache_create))
            c.commit()

    def test_low_cache_hit_emits_tip(self):
        self._ins("2026-04-15T00:00:00Z", "projX", 10, 1_000_000)
        tips = cache_discipline_tips(self.db, today_iso="2026-04-19T00:00:00")
        self.assertTrue(any(t["category"] == "cache" for t in tips))

    def test_healthy_cache_no_tip(self):
        for i in range(10):
            self._ins(f"2026-04-15T00:00:0{i}Z", "projY", 1_000_000, 50)
        tips = cache_discipline_tips(self.db, today_iso="2026-04-19T00:00:00")
        self.assertFalse(any(t["category"] == "cache" for t in tips))


class RepeatTipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        init_db(self.db)
        with connect(self.db) as c:
            c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model) VALUES ('m1','s1','p','assistant','2026-04-15T00:00:00Z','claude-opus-4-7')")
            for i in range(15):
                c.execute("INSERT INTO tool_calls (message_uuid, session_id, project_slug, tool_name, target, timestamp, is_error) VALUES ('m1','s1','p','Read','src/Root.tsx','2026-04-15T00:00:00Z',0)")
            for i in range(20):
                c.execute("INSERT INTO tool_calls (message_uuid, session_id, project_slug, tool_name, target, timestamp, is_error) VALUES ('m1','s1','p','Bash','npm run lint','2026-04-15T00:00:00Z',0)")
            c.commit()

    def test_repeated_file_and_bash_emit_tips(self):
        tips = repeated_target_tips(self.db, today_iso="2026-04-19T00:00:00")
        cats = [t["category"] for t in tips]
        self.assertIn("repeat-file", cats)
        self.assertIn("repeat-bash", cats)


class RightSizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        init_db(self.db)

    def test_short_opus_turns_flagged(self):
        with connect(self.db) as c:
            for i in range(10):
                c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens, cache_read_tokens, cache_create_5m_tokens, cache_create_1h_tokens, is_sidechain) VALUES (?, 's','p','assistant','2026-04-18T00:00:00Z','claude-opus-4-7', 1000000, 200, 0, 0, 0, 0)", (f"a{i}",))
            c.commit()
        tips = right_size_tips(self.db, _PRICING, today_iso="2026-04-19T00:00:00")
        self.assertTrue(any(t["category"] == "right-size" for t in tips))


class OutlierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        init_db(self.db)

    def test_giant_tool_result_flagged(self):
        with connect(self.db) as c:
            for i in range(20):
                c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp) VALUES (?, 's','p','user','2026-04-18T00:00:00Z')", (f"u{i}",))
                c.execute("INSERT INTO tool_calls (message_uuid, session_id, project_slug, tool_name, target, result_tokens, timestamp, is_error) VALUES (?, 's','p','_tool_result','tu',100000,'2026-04-18T00:00:00Z',0)", (f"u{i}",))
            c.commit()
        tips = outlier_tips(self.db, today_iso="2026-04-19T00:00:00")
        self.assertTrue(any(t["category"] == "tool-bloat" for t in tips))


class DismissTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        init_db(self.db)
        with connect(self.db) as c:
            c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens, cache_read_tokens, cache_create_5m_tokens, cache_create_1h_tokens) VALUES ('m','s','projZ','assistant','2026-04-15T00:00:00Z','claude-opus-4-7', 100, 100, 10, 1000000, 0)")
            c.commit()

    def test_dismissed_tip_doesnt_reappear(self):
        tips_before = cache_discipline_tips(self.db, today_iso="2026-04-19T00:00:00")
        self.assertTrue(tips_before)
        dismiss_tip(self.db, tips_before[0]["key"])
        tips_after = cache_discipline_tips(self.db, today_iso="2026-04-19T00:00:00")
        self.assertFalse(tips_after)


class BudgetTipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.db = os.path.join(self.tmp, "t.db"); init_db(self.db)
        with connect(self.db) as c:
            # ~$15 of opus input this month (1M input = $5 each)
            for i in range(3):
                c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, input_tokens) "
                          "VALUES (?, 's','p','assistant','2026-05-20T20:00:00Z','claude-opus-4-7',1000000)", (f"m{i}",))
            c.commit()
        self.now_iso = "2026-05-21T12:00:00"

    def test_fires_when_over_80pct(self):
        set_budget(self.db, 18)  # 15/18 = 83%
        tips = budget_tips(self.db, _PRICING, today_iso=self.now_iso)
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0]["category"], "budget")

    def test_silent_under_80pct(self):
        set_budget(self.db, 100)  # 15%
        self.assertEqual(budget_tips(self.db, _PRICING, today_iso=self.now_iso), [])

    def test_silent_when_unset(self):
        self.assertEqual(budget_tips(self.db, _PRICING, today_iso=self.now_iso), [])

    def test_all_tips_accepts_pricing(self):
        set_budget(self.db, 18)
        tips = all_tips(self.db, _PRICING, today_iso=self.now_iso)
        self.assertTrue(any(t["category"] == "budget" for t in tips))


class CostDriverTipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.db = os.path.join(self.tmp, "t.db"); init_db(self.db)
        self.now = "2026-05-21T12:00:00"

    def _a(self, uuid, sid, project, ts, model="claude-opus-4-7", inp=0, out=0, parent=None):
        with connect(self.db) as c:
            c.execute("INSERT INTO messages (uuid, parent_uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens) "
                      "VALUES (?, ?, ?, ?, 'assistant', ?, ?, ?, ?)", (uuid, parent, sid, project, ts, model, inp, out))
            c.commit()

    def _u(self, uuid, sid, project, ts):
        with connect(self.db) as c:
            c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, prompt_text) "
                      "VALUES (?, ?, ?, 'user', ?, 'do a thing')", (uuid, sid, project, ts))
            c.commit()

    def test_project_concentration_fires(self):
        self._a("a1", "s", "projA", "2026-05-20T12:00:00Z", inp=2_000_000)  # $10 opus input
        self._a("a2", "s", "projB", "2026-05-20T12:00:00Z", inp=200_000)    # $1 opus input
        tips = project_concentration_tips(self.db, _PRICING, today_iso=self.now)
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0]["category"], "cost-project")

    def test_expensive_prompt_fires(self):
        self._u("u1", "s", "projA", "2026-05-20T12:00:00Z")
        self._a("a1", "s", "projA", "2026-05-20T12:00:01Z", inp=0, out=200_000, parent="u1")  # $5 output
        tips = expensive_prompt_tips(self.db, _PRICING, today_iso=self.now)
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0]["category"], "cost-prompt")

    def test_cache_rebuild_fires(self):
        with connect(self.db) as c:
            c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, cache_create_5m_tokens) "
                      "VALUES ('a1','s','projA','assistant','2026-05-20T12:00:00Z','claude-opus-4-7',1000000)")  # $6.25, 100% cache-create
            c.commit()
        tips = cache_rebuild_cost_tips(self.db, _PRICING, today_iso=self.now)
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0]["category"], "cost-cache")

    def test_output_heavy_fires(self):
        self._a("a1", "s", "projA", "2026-05-20T12:00:00Z", out=200_000)  # $5, 100% output
        tips = output_heavy_tips(self.db, _PRICING, today_iso=self.now)
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0]["category"], "cost-output")

    def test_silent_when_cheap(self):
        self._a("a1", "s", "projA", "2026-05-20T12:00:00Z", inp=1000)  # ~$0.005
        self.assertEqual(project_concentration_tips(self.db, _PRICING, today_iso=self.now), [])
        self.assertEqual(cache_rebuild_cost_tips(self.db, _PRICING, today_iso=self.now), [])
        self.assertEqual(output_heavy_tips(self.db, _PRICING, today_iso=self.now), [])

    def test_all_tips_includes_cost_rules(self):
        self._a("a1", "s", "projA", "2026-05-20T12:00:00Z", inp=2_000_000)  # $10, one project
        cats = {t["category"] for t in all_tips(self.db, _PRICING, today_iso=self.now)}
        self.assertIn("cost-project", cats)


if __name__ == "__main__":
    unittest.main()
