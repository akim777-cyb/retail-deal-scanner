import unittest

from retail_scanner.geo import Geo, crexi_county_url


class GeoLookups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geo = Geo()

    def test_zip_to_msa(self):
        counties, _ = self.geo.counties_for("27707", "Durham", "NC")
        self.assertEqual(counties[0], "37063")                      # Durham County
        self.assertEqual(self.geo.cbsa_for("37063"), "20500")
        self.assertEqual(self.geo.msa_label("20500"), "Durham-Chapel Hill, NC")

    def test_zip_reaching_two_counties(self):
        counties, flags = self.geo.counties_for("27560", "Morrisville", "NC")
        self.assertEqual(counties[:2], ["37183", "37063"])          # Wake first (most land), Durham second
        self.assertTrue(any("also reaches" in f for f in flags))

    def test_connecticut_town_to_planning_region(self):
        counties, _ = self.geo.counties_for("06901", "Stamford", "CT")
        self.assertEqual(counties, ["09190"])                       # Western Connecticut Planning Region
        self.assertEqual(self.geo.msa_label(self.geo.cbsa_for("09190")), "Bridgeport-Stamford-Danbury, CT")

    def test_find_metro_and_micro(self):
        hits = self.geo.find_cbsa("Atlanta")
        self.assertEqual(hits[0][:2], ("12060", "Atlanta-Sandy Springs-Roswell, GA"))
        self.assertTrue(self.geo.msa_label("10100").endswith("(Micro)"))      # Aberdeen, SD

    def test_county_lookup_and_crexi_page(self):
        c = self.geo.find_county("Thurston County, WA")
        self.assertEqual(c["fips"], "53067")
        self.assertEqual(crexi_county_url(c), "https://www.crexi.com/properties/WA/Thurston_County/Retail")

    def test_principal_cities_title_order_and_clean_names(self):
        self.assertEqual([c["city"] for c in self.geo.principal_cities("20500")], ["Durham", "Chapel Hill"])
        self.assertEqual(self.geo.principal_cities("34980")[0]["city"], "Nashville")       # not "Nashville-Davidson metro..."
        self.assertEqual([c["city"] for c in self.geo.principal_cities("49180")], ["Winston-Salem"])

    def test_unknown_zip(self):
        counties, flags = self.geo.counties_for("00000")
        self.assertEqual(counties, [])
        self.assertTrue(flags)


if __name__ == "__main__":
    unittest.main()


class Locate(unittest.TestCase):
    def test_county_page_decides_when_the_zip_spans_counties(self):
        from retail_scanner.screening import locate
        geo = Geo()
        market = {"county_set": {"37063", "37135"}}                  # Durham and Orange
        x = {"zip": "27705", "city": "Durham", "state": "NC"}           # 27705: mostly Durham, also Orange
        self.assertTrue(locate(x, market, geo, hint="37135")[0])
        self.assertEqual(x["county_fips"], "37135")                     # read on the Orange County page
        y = {"zip": "27705", "city": "Durham", "state": "NC"}
        locate(y, market, geo)
        self.assertEqual(y["county_fips"], "37063")                     # no page: the ZIP's main county
