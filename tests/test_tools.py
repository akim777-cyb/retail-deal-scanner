import importlib.util
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("add_cards", os.path.join(REPO, "tools", "add_cards.py"))
add_cards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(add_cards)


class CardLineRepairs(unittest.TestCase):
    """Real slips from WebFetch reads of Crexi pages on 2026-11-21."""

    def test_clean_line(self):
        p = add_cards.split_line("main|Chipotle (Raleigh-Durham MSA)|2115 NC-54|Durham|NC|27713|$3,776,000|Retail|4.90%|2763|||")
        self.assertEqual(len(p), 13)
        self.assertEqual(p[8], "4.90%")

    def test_one_empty_field_too_many(self):
        p = add_cards.split_line("main|6453 North Carolina 55|6453 North Carolina 55|Durham|NC|27713|$3,900,000|"
                                 "Retail, Office, Special Purpose||||||Vacant RTP Area Daycare For Sale or Lease")
        self.assertEqual(len(p), 13)
        self.assertEqual(p[11], "Vacant RTP Area Daycare For Sale or Lease")       # tagline
        self.assertEqual(p[12], "")                                                 # no link

    def test_trailing_empties(self):
        p = add_cards.split_line("main|112 E. Main St|112 E MAIN ST|DURHAM|NC|27701-3602|$830,000|Retail||||||")
        self.assertEqual(len(p), 13)
        self.assertEqual(p[6], "$830,000")

    def test_tagline_in_link_field(self):
        p = add_cards.split_line("main|Kress Building|101 & 103 W Main St|Durham|NC|27701|$1,171,000|Retail, Office||4,574|||"
                                 "±4,574 SF Commercial Condo for Sale in Historic Kress Building in Downtown Durham")
        self.assertEqual(p[11], "±4,574 SF Commercial Condo for Sale in Historic Kress Building in Downtown Durham")
        self.assertEqual(p[12], "")

    def test_real_link_kept(self):
        p = add_cards.split_line("main|X|1 Main St|Durham|NC|27701|$1|Retail||||tag|https://www.crexi.com/properties/1/x")
        self.assertEqual(p[12], "https://www.crexi.com/properties/1/x")


if __name__ == "__main__":
    unittest.main()


class Prompts(unittest.TestCase):
    def test_results_prompt_carries_the_max_price(self):
        import contextlib, io
        from retail_scanner import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["prompt", "--kind", "results"])
        self.assertIn("asking price is above $5,000,000", buf.getvalue())
        self.assertIn("SKIPPED=", buf.getvalue())
