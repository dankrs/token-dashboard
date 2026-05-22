import os
import tempfile
import unittest

from token_dashboard.pricing import (
    load_pricing, cost_for, format_for_user, total_cost, get_budget, set_budget,
)
from token_dashboard.db import init_db

PRICING = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pricing.json"))


class CostTests(unittest.TestCase):
    def setUp(self):
        self.p = load_pricing(PRICING)

    def _u(self, **kw):
        base = {
            "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
            "cache_create_5m_tokens": 0, "cache_create_1h_tokens": 0,
        }
        base.update(kw)
        return base

    def test_known_opus_input_cost(self):
        c = cost_for("claude-opus-4-7", self._u(input_tokens=1_000_000), self.p)
        self.assertAlmostEqual(c["usd"], 5.00, places=4)
        self.assertFalse(c["estimated"])

    def test_known_sonnet_output_cost(self):
        c = cost_for("claude-sonnet-4-6", self._u(output_tokens=1_000_000), self.p)
        self.assertAlmostEqual(c["usd"], 15.00, places=4)

    def test_unknown_opus_falls_back(self):
        c = cost_for("claude-opus-9-9-experimental", self._u(input_tokens=1_000_000), self.p)
        self.assertAlmostEqual(c["usd"], 5.00, places=4)
        self.assertTrue(c["estimated"])

    def test_opus_rates_match_anthropic_published(self):
        """Regression guard: Opus 4.5+ is $5/$25, not the old $15/$75.

        Verified against platform.claude.com/docs pricing (May 2026):
        input $5, output $25, cache_read $0.50, 5m write $6.25, 1h write $10.
        """
        per_m = lambda **kw: cost_for("claude-opus-4-7", self._u(**kw), self.p)["usd"]
        self.assertAlmostEqual(per_m(input_tokens=1_000_000),           5.00, places=4)
        self.assertAlmostEqual(per_m(output_tokens=1_000_000),         25.00, places=4)
        self.assertAlmostEqual(per_m(cache_read_tokens=1_000_000),      0.50, places=4)
        self.assertAlmostEqual(per_m(cache_create_5m_tokens=1_000_000), 6.25, places=4)
        self.assertAlmostEqual(per_m(cache_create_1h_tokens=1_000_000), 10.00, places=4)

    def test_unknown_unparseable_returns_none(self):
        c = cost_for("custom-local-model", self._u(input_tokens=9999), self.p)
        self.assertIsNone(c["usd"])

    def test_cache_read_cheaper_than_input(self):
        c_in = cost_for("claude-opus-4-7", self._u(input_tokens=1_000_000), self.p)
        c_cr = cost_for("claude-opus-4-7", self._u(cache_read_tokens=1_000_000), self.p)
        self.assertLess(c_cr["usd"], c_in["usd"])


class PlanFormatTests(unittest.TestCase):
    def setUp(self):
        self.p = load_pricing(PRICING)

    def test_api_plan_returns_raw(self):
        out = format_for_user(12.34, "api", self.p)
        self.assertEqual(out["display_usd"], 12.34)
        self.assertIsNone(out["subscription_usd"])

    def test_pro_plan_returns_subscription_subtitle(self):
        out = format_for_user(12.34, "pro", self.p)
        self.assertEqual(out["subscription_usd"], 20)
        self.assertIn("Pro", out["subtitle"])


class TotalCostTests(unittest.TestCase):
    def setUp(self):
        self.p = load_pricing(PRICING)

    def _u(self, model, **kw):
        base = {"model": model, "input_tokens": 0, "output_tokens": 0,
                "cache_read_tokens": 0, "cache_create_5m_tokens": 0, "cache_create_1h_tokens": 0}
        base.update(kw)
        return base

    def test_total_cost_sums_rows(self):
        rows = [self._u("claude-opus-4-7", input_tokens=1_000_000),    # $5
                self._u("claude-sonnet-4-6", output_tokens=1_000_000)]  # $15
        self.assertAlmostEqual(total_cost(rows, self.p), 20.00, places=4)

    def test_total_cost_skips_unpriceable(self):
        rows = [self._u("claude-opus-4-7", input_tokens=1_000_000),
                self._u("custom-local-model", input_tokens=1_000_000)]  # usd None -> skipped
        self.assertAlmostEqual(total_cost(rows, self.p), 5.00, places=4)


class BudgetSettingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        init_db(self.db)

    def test_default_none_when_unset(self):
        self.assertIsNone(get_budget(self.db))

    def test_round_trip(self):
        set_budget(self.db, 300)
        self.assertAlmostEqual(get_budget(self.db), 300.0, places=4)

    def test_zero_round_trips_as_zero(self):
        set_budget(self.db, 0)
        self.assertEqual(get_budget(self.db), 0.0)


if __name__ == "__main__":
    unittest.main()
