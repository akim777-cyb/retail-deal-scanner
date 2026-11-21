import os
import tempfile
import unittest

from retail_scanner.ledger import Ledger, change_since_export


def card(**kw):
    x = {"name": "Garfield Landing", "address": "41560 Garfield Rd", "city": "Clinton Township", "state": "MI",
         "zip": "48038", "price": 1_895_000, "sf": 14800, "status": "Active", "flags": [], "sources": ["crexi results page"]}
    x.update(kw)
    return x


class Ledgering(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.led = Ledger(os.path.join(self.tmp, "m.jsonl"))

    def test_new_then_updated_then_price_change(self):
        self.assertEqual(self.led.upsert(card(), "2026-11-01")[0], "new")
        self.assertEqual(self.led.upsert(card(), "2026-11-08")[0], "updated")
        what, key = self.led.upsert(card(price=1_795_000), "2026-11-15")
        self.assertEqual(what, "price change")
        x = self.led.items[key]
        self.assertEqual(x["price_history"], [["2026-11-01", 1_895_000], ["2026-11-15", 1_795_000]])
        self.assertEqual(x["first_seen"], "2026-11-01")
        self.assertEqual(x["last_seen"], "2026-11-15")

    def test_two_spellings_one_property(self):
        self.led.upsert(card(name="2900-2924 Minnesota Avenue", address="2900-2924 Minnesota Ave SE", zip="20019", sf=12000))
        what, _ = self.led.upsert(card(name="Entire city block", address="2900 Minnesota Avenue SE", zip="20019", sf=12100))
        self.assertEqual(what, "updated")
        self.assertEqual(len(self.led.items), 1)

    def test_portfolio_and_single_stay_apart(self):
        self.led.upsert(card(name="112 N Mineral Springs Rd", address="112 N Mineral Springs Rd", zip="27703", price=195000))
        self.led.upsert(card(name="116 N Mineral Springs Rd", address="112 N Mineral Springs Rd", zip="27703", price=None,
                             flags=["portfolio (2 locations)"]))
        self.assertEqual(len(self.led.items), 2)

    def test_county_page_and_city_page_spell_one_listing_two_ways(self):
        # Crexi 2026-11-21: county page "116 N Mineral Springs Rd" at 112 N Mineral Springs Rd (2 LOCATIONS);
        # city page the same title at 116 N Mineral Springs Rd, no tagline.
        self.led.upsert(card(name="112 N Mineral Springs Rd", address="112 N Mineral Springs Rd", zip="27703",
                             price=195000, county_fips="37063"))
        self.led.upsert(card(name="116 N Mineral Springs Rd", address="112 N Mineral Springs Rd", zip="27703", price=None,
                             sf=None, county_fips="37063", flags=["portfolio (2 locations)"]))
        what, key = self.led.upsert(card(name="116 N Mineral Springs Rd", address="116 N Mineral Springs Rd", zip="27703",
                                         price=None, sf=None, county_fips="37063"))
        self.assertEqual(what, "updated")
        self.assertTrue(key.startswith("portfolio:"))
        self.assertEqual(len(self.led.items), 2)

    def test_real_near_misses_stay_apart(self):
        # all four were wrongly merged by the first version of the loose match (Crexi reads, 2026-11-21)
        pairs = [
            (card(name="112 W Main St", address="112 W Main St", zip="27701", price=2_950_000, sf=9250),
             card(name="112 E. Main St", address="112 E MAIN ST", zip="27701", price=830_000, sf=None)),
            (card(name="Suite 305 at The Fountains", address="308 W Rosemary Street, Suite 305", zip="27516", price=163_000, sf=1123),
             card(name="Suite 307 at The Fountains", address="308 W Rosemary Street, Suite 307", zip="27516", price=178_000, sf=1211)),
            (card(name="308 West Rosemary Street, Suite 101, 102, and 103", address="308 W Rosemary St", zip="27516", price=685_000, sf=None),
             card(name="308 W Rosemary Street Units 101 & 102", address="308 W Rosemary St Units 101 & 102", zip="27516", price=410_000, sf=None)),
            (card(name="Willow Creek Professional Center", address="610 Jones Ferry Rd", zip="27510", price=399_000, sf=3054, county_fips="37135"),
             card(name="Willow Creek Professional Center", address="610 Jones Ferry Rd, Suite 205", zip="27510", price=650_000, sf=5030, county_fips="37135")),
        ]
        for a, b in pairs:
            led = Ledger(os.path.join(tempfile.mkdtemp(), "m.jsonl"))
            led.upsert(a)
            self.assertEqual(led.upsert(b)[0], "new", b["name"])

    def test_generic_titles_do_not_merge(self):
        self.led.upsert(card(name="Retail Building", address="10 A St", zip="27703", county_fips="37063"))
        self.led.upsert(card(name="Retail Building", address="900 Z Ave", zip="27703", county_fips="37063"))
        self.assertEqual(len(self.led.items), 2)

    def test_save_and_load(self):
        self.led.upsert(card())
        self.led.save()
        again = Ledger(self.led.path)
        self.assertEqual(list(again.items), list(self.led.items))


class ExportTracking(unittest.TestCase):
    def setUp(self):
        self.led = Ledger(os.path.join(tempfile.mkdtemp(), "m.jsonl"))
        _, self.key = self.led.upsert(card(), "2026-11-01")

    def x(self):
        return self.led.items[self.key]

    def test_new_until_exported(self):
        self.assertEqual(change_since_export(self.x()), ("New", True))
        self.led.mark_exported([self.key], "2026-11-01", "new")
        label, include = change_since_export(self.x())
        self.assertFalse(include)
        self.assertEqual(label, "Exported 2026-11-01")

    def test_price_cut_comes_back(self):
        self.led.mark_exported([self.key], "2026-11-01", "new")
        self.led.upsert(card(price=1_700_000), "2026-11-10")
        label, include = change_since_export(self.x())
        self.assertTrue(include)
        self.assertTrue(label.startswith("Price cut from $1,895,000"))

    def test_price_raise_stays_out_by_default(self):
        self.led.mark_exported([self.key], "2026-11-01", "new")
        self.led.upsert(card(price=1_995_000), "2026-11-10")
        self.assertFalse(change_since_export(self.x())[1])
        self.assertTrue(change_since_export(self.x(), include_raises=True)[1])

    def test_now_priced(self):
        _, k = self.led.upsert(card(address="5600 S Miami Blvd", zip="27560", name="5600 S Miami Blvd", price=None))
        self.led.mark_exported([k], "2026-11-01", "new")
        self.led.upsert(card(address="5600 S Miami Blvd", zip="27560", name="5600 S Miami Blvd", price=3_100_000))
        self.assertTrue(change_since_export(self.led.items[k])[0].startswith("Now priced"))

    def test_listing_page_read_comes_back_once(self):
        self.led.mark_exported([self.key], "2026-11-01", "new")
        self.x()["confirmed"] = True
        self.assertTrue(change_since_export(self.x())[1])
        self.led.mark_exported([self.key], "2026-11-02", "new")
        self.assertFalse(change_since_export(self.x())[1])

    def test_pass_stays_out_unless_price_drops(self):
        self.led.review(self.key, "pass", "too small", "2026-11-02")
        self.assertFalse(change_since_export(self.x())[1])
        self.led.upsert(card(price=1_850_000), "2026-11-09")            # 2.4% cut: still out
        self.assertFalse(change_since_export(self.x())[1])
        self.led.upsert(card(price=1_750_000), "2026-11-16")            # 7.7% cut: back in
        label, include = change_since_export(self.x())
        self.assertTrue(include)
        self.assertIn("since marked pass", label)

    def test_clear_review(self):
        self.led.review(self.key, "pursue")
        self.led.review(self.key, "clear")
        self.assertNotIn("review", self.x())
        with self.assertRaises(ValueError):
            self.led.review(self.key, "maybe")


if __name__ == "__main__":
    unittest.main()
