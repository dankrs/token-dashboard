import http.server
import json
import os
import socket
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from token_dashboard.db import init_db
from token_dashboard.server import build_handler


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        init_db(self.db)
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO messages (uuid, parent_uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens, cache_read_tokens, cache_create_5m_tokens, cache_create_1h_tokens, prompt_text, prompt_chars) VALUES ('u',NULL,'s','p','user','2026-04-19T00:00:00Z',NULL,0,0,0,0,0,'hi',2)")
            c.execute("INSERT INTO messages (uuid, parent_uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens, cache_read_tokens, cache_create_5m_tokens, cache_create_1h_tokens) VALUES ('a','u','s','p','assistant','2026-04-19T00:00:01Z','claude-haiku-4-5',1,1,0,0,0)")
            c.commit()
        self.port = _free_port()
        H = build_handler(self.db, projects_dir="/nonexistent")
        self.httpd = http.server.HTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()

    def _get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}").read()

    def test_index_html(self):
        body = self._get("/")
        self.assertIn(b"Token Dashboard", body)

    def test_overview_json(self):
        body = json.loads(self._get("/api/overview"))
        self.assertIn("sessions", body)
        self.assertEqual(body["sessions"], 1)

    def test_prompts_json(self):
        body = json.loads(self._get("/api/prompts?limit=10"))
        self.assertIsInstance(body, list)

    def test_projects_json(self):
        body = json.loads(self._get("/api/projects"))
        self.assertIsInstance(body, list)
        self.assertEqual(body[0]["project_slug"], "p")

    def test_plan_json(self):
        body = json.loads(self._get("/api/plan"))
        self.assertIn("plan", body)
        self.assertIn("pricing", body)

    def test_head_returns_200_not_501(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/", method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read(), b"")

    def test_head_api_endpoint(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/overview", method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read(), b"")

    def _post(self, path, obj):
        data = json.dumps(obj).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())

    def test_live_json_shape(self):
        body = json.loads(self._get("/api/live"))
        self.assertIn("active", body)
        self.assertIn("today", body)
        self.assertIn("cost_usd", body["today"])
        # fixture has one haiku assistant msg -> active is present
        self.assertIsNotNone(body["active"])
        self.assertEqual(body["active"]["session_id"], "s")

    def test_cost_daily_json(self):
        body = json.loads(self._get("/api/cost-daily"))
        self.assertIsInstance(body, list)

    def test_cost_drivers_json_shape(self):
        body = json.loads(self._get("/api/cost-drivers"))
        self.assertIn("total_usd", body)
        self.assertIn("by_type", body)
        self.assertIn("by_model", body)
        self.assertIn("by_project", body)

    def test_trends_json_shape(self):
        body = json.loads(self._get("/api/trends"))
        self.assertIn("budget", body)
        self.assertIn("periods", body)
        self.assertIn("status", body["budget"])

    def test_post_budget_sets_value(self):
        status, body = self._post("/api/budget", {"monthly_usd": 250})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        trends = json.loads(self._get("/api/trends"))
        self.assertEqual(trends["budget"]["monthly_usd"], 250.0)

    def test_post_budget_rejects_junk(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/budget",
                                     data=json.dumps({"monthly_usd": "abc"}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
