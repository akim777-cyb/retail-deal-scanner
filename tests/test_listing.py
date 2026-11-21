import unittest

from retail_scanner.listing import (acres, addr_key, classify, listing_key, match_key, money, occupancy, pct, price_basis,
                                    sqft, year, zip5)


class Parsing(unittest.TestCase):
    def test_money(self):
        self.assertEqual(money("$2,116,000"), 2116000)
        self.assertIsNone(money("Unpriced"))
        self.assertIsNone(money("$11/SF"))
        self.assertEqual(money("$1.5M"), 1_500_000)
        self.assertEqual(money("$350K"), 350_000)
        self.assertEqual(money(4424000), 4424000)

    def test_price_basis(self):
        self.assertEqual(price_basis("$11/SF"), "per_sf")
        self.assertEqual(price_basis("Unpriced"), "unpriced")
        self.assertEqual(price_basis("$1,000,000 - $1,200,000"), "range")
        self.assertEqual(price_basis("$4,424,000"), "total")

    def test_cap_rate(self):
        self.assertAlmostEqual(pct("8.25%"), 0.0825)
        self.assertAlmostEqual(pct("6.65"), 0.0665)
        self.assertAlmostEqual(pct(0.07), 0.07)
        self.assertIsNone(pct("0.00%"))
        self.assertIsNone(pct("45%"))
        self.assertIsNone(pct(""))

    def test_occupancy(self):
        self.assertEqual(occupancy("100% Occupied"), 1.0)
        self.assertAlmostEqual(occupancy("12 of 14 units leased"), 12 / 14)
        self.assertEqual(occupancy("Fully Leased"), 1.0)
        self.assertAlmostEqual(occupancy("85% Leased"), 0.85)
        self.assertAlmostEqual(occupancy(95), 0.95)
        self.assertIsNone(occupancy("Established tenant in place through 2028"))

    def test_sizes_and_years(self):
        self.assertEqual(sqft("14,800 SqFt"), 14800)
        self.assertEqual(sqft("±4,574 SF"), 4574)
        self.assertIsNone(sqft("1.92 acres"))
        self.assertAlmostEqual(acres("43,560 SF"), 1.0)
        self.assertEqual(acres("1.92 acres"), 1.92)
        self.assertEqual(year("Built 2006"), 2006)
        self.assertEqual(zip5("28056-7262"), "28056")


class Caps(unittest.TestCase):
    def test_tidy_caps(self):
        from retail_scanner.listing import tidy_caps
        self.assertEqual(tidy_caps("112 E MAIN ST"), "112 E Main St")
        self.assertEqual(tidy_caps("2104 US HWY 70 E"), "2104 US Hwy 70 E")
        self.assertEqual(tidy_caps("4100 Menaul Blvd NE"), "4100 Menaul Blvd NE")      # mixed case left alone


class Keys(unittest.TestCase):
    def test_same_address_two_spellings(self):
        self.assertEqual(addr_key("112 North Mineral Springs Road", "27703"), addr_key("112 N Mineral Springs Rd", "27703"))

    def test_loose_key_catches_number_ranges(self):
        self.assertEqual(match_key("2900-2924 Minnesota Ave SE", "20019"), match_key("2900 Minnesota Avenue SE", "20019"))
        self.assertNotEqual(match_key("4100 Durham-Chapel Hill Blvd", "27707"), match_key("4010 Durham-Chapel Hill Blvd", "27707"))

    def test_portfolio_gets_its_own_key(self):
        single = {"address": "112 N Mineral Springs Rd", "zip": "27703", "flags": []}
        port = {"address": "112 N Mineral Springs Rd", "zip": "27703", "flags": ["portfolio (2 locations)"]}
        self.assertNotEqual(listing_key(single), listing_key(port))


class Kinds(unittest.TestCase):
    def k(self, types, name, tagline="", sf=None):
        return classify(types, name, tagline, sf)[0]

    def test_kinds(self):
        self.assertEqual(self.k("Retail", "Strip Center - Naperville, IL", "", 22300), "Multi-Tenant Center")
        self.assertEqual(self.k("Retail", "Two-tenant Food Lion Shadow Anchored Retail Strip"), "Multi-Tenant Center")
        self.assertEqual(self.k("Retail", "Dollar General", "15-Year Absolute NNN"), "Single-Tenant NNN")
        self.assertEqual(self.k("Retail, Land", "4017 Angier Ave", "Great location corner lot in Durham"), "Land / Pad Site")
        self.assertEqual(self.k("Retail, Land", "Imperial Center Business Park", "Land • 1.92 acres"), "Land / Pad Site")
        self.assertEqual(self.k("Retail", "Established Indian Grocery Store Business -WAR108"), "Business Sale")
        self.assertEqual(self.k("Retail, Industrial", "1023 S Miami BLVD", "Standalone Flex Building For Sale or Lease"),
                         "Flex / Industrial")
        self.assertEqual(self.k("Hospitality, Retail, Special Purpose", "Topgolf / 20-Yr Abs NNN"), "Hospitality")
        self.assertEqual(self.k("Retail, Office, Mixed Use", "112 W Main St", "", 9250), "Retail / Mixed Use")
        self.assertNotEqual(self.k("Retail", "Chipotle & Mattress Warehouse"), "Flex / Industrial")
        self.assertNotEqual(self.k("Retail", "1016 Industrial Pkwy", "", 6008), "Flex / Industrial")

    def test_flags(self):
        _, _, flags = classify("Retail, Office", "Kress Building", "Commercial Condo in Historic Kress Building", 4574)
        self.assertIn("condo unit", flags)
        _, _, flags = classify("Retail", "116 N Mineral Springs Rd", "2 LOCATIONS")
        self.assertIn("portfolio (2 locations)", flags)


if __name__ == "__main__":
    unittest.main()
