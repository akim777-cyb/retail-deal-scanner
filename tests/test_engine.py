import json
import os
import unittest

from retail_scanner.engine import loan_constant, passes, underwrite

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "profiles", "retail_pe.json"), encoding="utf-8") as _f:
    PROFILE = json.load(_f)
UW = {"vacancy_credit_loss": 0.05, "management_pct": 0.0, "reserves_psf": 0.20, "closing_costs_pct": 0.02,
      "target_cap": 0.08, "loan": {"ltv": 0.65, "rate": 0.0675, "amort_years": 25}}


class LoanMath(unittest.TestCase):
    def test_constant(self):
        # $100,000 at 6.75% over 25 years pays $690.91 a month (standard amortization tables): $8,290.94 a year.
        self.assertAlmostEqual(loan_constant(0.0675, 25) * 100000 / 12, 690.91, places=2)
        self.assertAlmostEqual(loan_constant(0.0, 25), 0.04)


class FirstPass(unittest.TestCase):
    def test_dayton_three_tenant_center(self):
        # Crexi card 2026-11-21: 3950 Linden Ave, Dayton OH, $1,500,000, 7.81% cap, 11,918 SF, fully leased
        r = underwrite(1_500_000, UW, cap=0.0781, sf=11918)
        self.assertEqual(r["noi_source"], "implied")
        self.assertAlmostEqual(r["noi_basis"], 117_150)                 # 1,500,000 x 7.81%
        self.assertAlmostEqual(r["uw_noi"], 117_150 * 0.95 - 0.20 * 11918)  # 108,908.9
        self.assertAlmostEqual(r["loan"], 975_000)
        self.assertAlmostEqual(r["debt_service"], 975_000 * loan_constant(0.0675, 25))
        self.assertAlmostEqual(r["dscr"], 108_908.9 / (975_000 * loan_constant(0.0675, 25)), places=6)
        self.assertAlmostEqual(r["equity"], 1_500_000 * 0.35 + 1_500_000 * 0.02)
        self.assertAlmostEqual(r["price_at_target"], 108_908.9 / 0.08)
        ok, why = passes(r, 1.0, PROFILE["first_pass"])
        self.assertTrue(ok, why)

    def test_tight_cap_fails(self):
        r = underwrite(4_424_000, UW, cap=0.06, sf=8297)
        ok, why = passes(r, None, PROFILE["first_pass"])
        self.assertFalse(ok)
        self.assertIn("DSCR", why[0])

    def test_listed_noi_wins_and_mismatch_is_noted(self):
        r = underwrite(2_000_000, UW, noi=150_000, cap=0.08, sf=20000)
        self.assertEqual(r["noi_source"], "listed")
        self.assertAlmostEqual(r["noi_basis"], 150_000)
        self.assertTrue(any("implies a 7.50% cap" in n for n in r["notes"]))

    def test_no_noi_no_first_pass(self):
        r = underwrite(2_950_000, UW, sf=9250)
        self.assertIsNone(r["dscr"])
        ok, why = passes(r, None, PROFILE["first_pass"])
        self.assertFalse(ok)
        self.assertEqual(why, ["no NOI or cap rate shown"])

    def test_no_size_no_reserves(self):
        r = underwrite(1_000_000, UW, cap=0.08)
        self.assertEqual(r["reserves"], 0.0)
        self.assertTrue(any("no reserves" in n for n in r["notes"]))

    def test_profile_matches_defaults_used_here(self):
        self.assertEqual(PROFILE["buy_box"]["max_price"], 5_000_000)
        self.assertEqual(PROFILE["underwriting"]["loan"], UW["loan"])


if __name__ == "__main__":
    unittest.main()
