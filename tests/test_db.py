import os
import sqlite3
import tempfile
import unittest
from token_dashboard.db import init_db, connect, daily_model_breakdown, daily_token_breakdown


class InitDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")

    def test_init_creates_expected_tables(self):
        init_db(self.db_path)
        with sqlite3.connect(self.db_path) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {"files", "messages", "tool_calls", "plan", "dismissed_tips"}
        self.assertTrue(expected.issubset(tables), f"Missing: {expected - tables}")

    def test_init_is_idempotent(self):
        init_db(self.db_path)
        init_db(self.db_path)

    def test_connect_returns_row_factory(self):
        init_db(self.db_path)
        with connect(self.db_path) as c:
            r = c.execute("SELECT 1 AS one").fetchone()
        self.assertEqual(r["one"], 1)


class DailyLocalBucketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        init_db(self.db)
        with connect(self.db) as c:
            # 01:30 UTC -> previous day at UTC-5; 20:00 UTC -> same day
            c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens) VALUES ('a1','s','p','assistant','2026-05-12T01:30:00.000Z','claude-opus-4-7',100,10)")
            c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens) VALUES ('a2','s','p','assistant','2026-05-12T20:00:00.000Z','claude-opus-4-7',200,20)")
            c.execute("INSERT INTO messages (uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens) VALUES ('a3','s','p','assistant','2026-05-12T21:00:00.000Z','claude-sonnet-4-6',5,5)")
            c.commit()

    def test_model_breakdown_buckets_by_local_day(self):
        rows = daily_model_breakdown(self.db, day_modifier="-5 hours")
        days = sorted({r["day"] for r in rows})
        self.assertEqual(days, ["2026-05-11", "2026-05-12"])
        opus_0512 = [r for r in rows if r["day"] == "2026-05-12" and r["model"] == "claude-opus-4-7"][0]
        self.assertEqual(opus_0512["input_tokens"], 200)

    def test_model_breakdown_utc_modifier_groups_same_day(self):
        rows = daily_model_breakdown(self.db, day_modifier="+00:00")
        self.assertEqual(sorted({r["day"] for r in rows}), ["2026-05-12"])

    def test_token_breakdown_accepts_modifier(self):
        rows = daily_token_breakdown(self.db, day_modifier="-5 hours")
        self.assertEqual(sorted(r["day"] for r in rows), ["2026-05-11", "2026-05-12"])


if __name__ == "__main__":
    unittest.main()
