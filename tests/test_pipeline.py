"""End to end in a scratch folder: market pack -> page reads -> ledger -> Excel -> re-export only what changed."""
import contextlib
import io
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from openpyxl import load_workbook

from retail_scanner import cli, workbook

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(REPO, "tests", "fixtures", "crexi_durham_county_2026-11-21.txt")
DURHAM_PAGE = "https://www.crexi.com/properties/NC/Durham_County/Retail"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(list(argv))
    return buf.getvalue()


def add_cards(run_dir, market, county, text, source, page="1"):
    p = subprocess.run([sys.executable, os.path.join(REPO, "tools", "add_cards.py"), "--run-dir", run_dir, "--market", market,
                        "--county", county, "--source", source, "--page", page], input=text, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout


def rows_of(path, sheet):
    ws = load_workbook(path)[sheet]
    head = [c.value for c in ws[1]]
    return head, [dict(zip(head, [c.value for c in r])) for r in ws.iter_rows(min_row=2)], ws


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        shutil.copytree(os.path.join(REPO, "profiles"), os.path.join(self.home, "profiles"))
        self.saved_root, cli.ROOT = cli.ROOT, self.home

    def tearDown(self):
        cli.ROOT = self.saved_root
        shutil.rmtree(self.home, ignore_errors=True)

    def durham(self):
        run("new-market", "--key", "durham", "--cbsa", "20500")
        d = os.path.join(self.home, "runs", "1")
        out = add_cards(d, "durham", "37063", read(FIXTURE), DURHAM_PAGE)
        self.assertIn("listed 26, skipped 0, suggested 20, bad 0, total shown 26 -> LAST PAGE", out)
        run("ingest", "--market", "durham", "--run-dir", d, "--seen", "2026-11-21")

    def test_durham_read_to_excel_and_only_changes_after(self):
        self.durham()
        ledger = [json.loads(l) for l in read(os.path.join(self.home, "data", "ledger", "deals.jsonl")).splitlines()]
        self.assertEqual(len(ledger), 26)                       # every main card, the portfolio kept apart
        x1 = os.path.join(self.home, "first.xlsx")
        report = run("build", "--market", "durham", "--out", x1)
        self.assertIn("pages not read: Chatham County, NC; Orange County, NC; Person County, NC; Durham, NC (city page); "
                      "Chapel Hill, NC (city page)", report)
        head, rows, ws = rows_of(x1, "All Properties")
        self.assertEqual(head, [c[0] for c in workbook.COLUMNS])
        addresses = {r["Listing"] for r in rows}
        for inside in ("4100 Durham-Chapel Hill Blvd", "2115 NC-54", "101 & 103 W Main St", "4511 Hopson Rd"):
            self.assertIn(inside, addresses)
        for outside in ("4901 Topgolf Wy", "4010 Durham-Chapel Hill Blvd", "4017 Angier Ave", "1023 S Miami Blvd",
                        "Slater Road at Parliament Court", "804 Madison Street"):
            self.assertNotIn(outside, addresses)
        self.assertFalse(any("Grocery Store Business" in (r["Property"] or "") for r in rows))
        self.assertTrue(all(r["MSA"] == "Durham-Chapel Hill, NC" for r in rows))
        self.assertTrue(ws["A2"].hyperlink.target.startswith("https://www.google.com/search?q=crexi"))
        star = next(r for r in rows if r["Listing"] == "4100 Durham-Chapel Hill Blvd")
        self.assertEqual(star["Ask"], 4_424_000)
        self.assertAlmostEqual(star["Cap Rate"], 0.06)
        self.assertEqual(star["NOI"], 265_440)                   # 4,424,000 x 6.00%, shown as an estimate
        self.assertEqual(star["Change"], "New")
        self.assertLess(star["DSCR"], 1.25)
        _, first, _ = rows_of(x1, "First Pass")
        self.assertEqual(first, [])
        # second export with nothing new: no Excel
        x2 = os.path.join(self.home, "second.xlsx")
        out = run("build", "--market", "durham", "--out", x2)
        self.assertIn("Nothing new or changed", out)
        self.assertFalse(os.path.exists(x2))
        # a price cut comes back on its own
        d2 = os.path.join(self.home, "runs", "2")
        cut = read(FIXTURE).replace("|$3,776,000|", "|$3,400,000|")
        add_cards(d2, "durham", "37063", cut, DURHAM_PAGE)
        run("ingest", "--market", "durham", "--run-dir", d2, "--seen", "2026-11-28")
        x3 = os.path.join(self.home, "third.xlsx")
        run("build", "--market", "durham", "--out", x3)
        _, rows3, _ = rows_of(x3, "All Properties")
        self.assertEqual([r["Listing"] for r in rows3], ["2115 NC-54"])
        self.assertTrue(rows3[0]["Change"].startswith("Price cut from $3,776,000"))
        # a pass keeps it out, a small cut does not bring it back
        run("mark", "--market", "durham", "--listing", "2115 NC-54", "--status", "pass", "--note", "4.9% cap")
        d3 = os.path.join(self.home, "runs", "3")
        add_cards(d3, "durham", "37063", cut.replace("|$3,400,000|", "|$3,350,000|"), DURHAM_PAGE)
        run("ingest", "--market", "durham", "--run-dir", d3, "--seen", "2026-12-05")
        self.assertIn("Nothing new or changed", run("build", "--market", "durham", "--out", os.path.join(self.home, "4.xlsx")))
        # a full export still lists everything, with why each one is there
        x5 = os.path.join(self.home, "full.xlsx")
        run("build", "--market", "durham", "--mode", "full", "--out", x5, "--no-mark")
        _, rows5, _ = rows_of(x5, "All Properties")
        self.assertEqual(len(rows5), len(rows))
        self.assertTrue(next(r for r in rows5 if r["Listing"] == "2115 NC-54")["Change"].startswith("Marked pass"))

    def test_gone_only_when_every_page_it_was_on_is_reread_without_it(self):
        self.durham()
        city = "main|The bartlett|1105 W Main Street Ste 100|Durham|NC|27701|$2,800,000|Retail||5,985|||\nTOTAL=1; CARDS=1; NEXT=none\n"
        d1 = os.path.join(self.home, "runs", "c")
        add_cards(d1, "durham", "37063", city, "https://www.crexi.com/properties/NC/DURHAM/Retail")
        p = subprocess.run([sys.executable, os.path.join(REPO, "tools", "add_cards.py"), "--run-dir", d1, "--market", "durham",
                            "--county", "37063", "--page-id", "city:Durham, NC", "--source", "x"], input=city,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        run("ingest", "--market", "durham", "--run-dir", d1, "--seen", "2026-11-21")
        # a week later only the county page is read again, and the Chipotle card is gone from it
        d2 = os.path.join(self.home, "runs", "later")
        gone = "\n".join(l for l in read(FIXTURE).splitlines() if "2115 NC-54" not in l).replace("TOTAL=26", "TOTAL=25")
        add_cards(d2, "durham", "37063", gone, DURHAM_PAGE)
        run("ingest", "--market", "durham", "--run-dir", d2, "--seen", "2026-11-28")
        x = os.path.join(self.home, "full.xlsx")
        report = run("build", "--market", "durham", "--mode", "full", "--out", x, "--no-mark")
        self.assertIn("no longer listed (gone from every page it was on) | 1 |", report)
        _, rows, _ = rows_of(x, "All Properties")
        listed = {r["Listing"] for r in rows}
        self.assertNotIn("2115 NC-54", listed)                         # gone from the only page it was on
        self.assertIn("1105 W Main Street Ste 100", listed)            # its city page was not read again: kept

    def test_first_pass_and_listing_page_read(self):
        run("new-market", "--key", "dayton", "--cbsa", "19430")
        d = os.path.join(self.home, "runs", "d")
        add_cards(d, "dayton", "39113", "main|Fully Leased, Newly Renovated 3 Tenant Center - Retail|3950 Linden Ave|Dayton|OH|"
                  "45432|$1,500,000|Retail|7.81%|11,918 SqFt|Fully Leased||\nTOTAL=1; CARDS=1; NEXT=none\n",
                  "https://www.crexi.com/properties/OH/Montgomery_County/Retail")
        run("ingest", "--market", "dayton", "--run-dir", d, "--seen", "2026-11-21")
        x1 = os.path.join(self.home, "dayton.xlsx")
        report = run("build", "--market", "dayton", "--out", x1)
        self.assertIn("1 First Pass listings not opened yet", report)
        _, first, _ = rows_of(x1, "First Pass")
        self.assertEqual(len(first), 1)
        self.assertAlmostEqual(first[0]["DSCR"], 1.35, places=2)
        self.assertEqual(first[0]["Occupancy"], 1.0)
        self.assertIn("3950 Linden Ave|Dayton|OH|45432|First Pass", run("todo", "--market", "dayton"))
        page = ("Active|Retail|Strip Center|$1,500,000|7.81%|$117,150|11,918|1.1|1986|100%|Multiple|3|"
                "Dollar General; Subway; H&R Block|NNN|4.2|Jane Doe|Example Realty|45 days|\nNOTE: three national tenants\n")
        p = subprocess.run([sys.executable, os.path.join(REPO, "tools", "add_details.py"), "--run-dir", d, "--address",
                            "3950 Linden Ave", "--zip", "45432", "--url", "https://www.crexi.com/properties/123456/ohio-3950-linden",
                            "--read-on", "2026-11-22"], input=page, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        run("ingest", "--market", "dayton", "--run-dir", d, "--seen", "2026-11-22")
        x2 = os.path.join(self.home, "dayton2.xlsx")
        run("build", "--market", "dayton", "--out", x2, "--as-of", "2026-11-22")
        head, rows, ws = rows_of(x2, "First Pass")
        r = rows[0]
        self.assertTrue(r["Change"].startswith("Listing page read since export"))
        self.assertEqual(r["Tenants"], "Dollar General; Subway; H&R Block")
        self.assertEqual(r["Type"], "Multi-Tenant Center")
        self.assertEqual(r["NOI"], 117_150)
        self.assertEqual(ws["A2"].hyperlink.target, "https://www.crexi.com/properties/123456/ohio-3950-linden")
        self.assertEqual(r["Broker"], "Jane Doe / Example Realty")
        self.assertEqual(r["WALT (Yrs)"], 4.2)
        self.assertEqual(r["Days on Market"], 45)                     # 45 days on market on the page read 11/22
        self.assertEqual(ws.cell(2, head.index("Days on Market") + 1).number_format, "0")
        # read at today's price: not opened again; a price cut puts it back on the list
        self.assertIn("0 of 0 listing pages worth opening", run("todo", "--market", "dayton", "--as-of", "2026-11-23"))
        d2 = os.path.join(self.home, "runs", "d2")
        add_cards(d2, "dayton", "39113", "main|Fully Leased, Newly Renovated 3 Tenant Center - Retail|3950 Linden Ave|Dayton|OH|"
                  "45432|$1,400,000|Retail|8.37%|11,918 SqFt|Fully Leased||\nTOTAL=1; CARDS=1; NEXT=none\n",
                  "https://www.crexi.com/properties/OH/Montgomery_County/Retail")
        run("ingest", "--market", "dayton", "--run-dir", d2, "--seen", "2026-12-02")
        self.assertIn("3950 Linden Ave|Dayton|OH|45432|First Pass", run("todo", "--market", "dayton", "--as-of", "2026-12-02"))
        x3 = os.path.join(self.home, "dayton3.xlsx")
        run("build", "--market", "dayton", "--out", x3, "--as-of", "2026-12-02")
        _, rows3, _ = rows_of(x3, "First Pass")
        self.assertEqual(rows3[0]["Days on Market"], 55)                # still counted from the listed-on date


if __name__ == "__main__":
    unittest.main()


class Efficiency(unittest.TestCase):
    """The running log: one ledger for every market, pages not re-read too soon, the Deal Log workbook."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        shutil.copytree(os.path.join(REPO, "profiles"), os.path.join(self.home, "profiles"))
        self.saved_root, cli.ROOT = cli.ROOT, self.home
        run("new-market", "--key", "durham", "--cbsa", "20500")
        self.run_dir = os.path.join(self.home, "runs", "1")
        add_cards(self.run_dir, "durham", "37063", read(FIXTURE), DURHAM_PAGE)
        run("ingest", "--market", "durham", "--run-dir", self.run_dir, "--seen", "2026-11-21")

    def tearDown(self):
        cli.ROOT = self.saved_root
        shutil.rmtree(self.home, ignore_errors=True)

    def test_a_deal_exported_in_one_market_is_not_exported_again_in_another(self):
        run("new-market", "--key", "durham_county", "--counties", "Durham County, NC", "--name", "Durham County only")
        first = run("build", "--market", "durham", "--out", os.path.join(self.home, "a.xlsx"))
        exported = int(re.search(r"\| in the buy box \| (\d+) \|", first).group(1))
        self.assertGreater(exported, 0)
        out = run("build", "--market", "durham_county", "--out", os.path.join(self.home, "b.xlsx"))
        self.assertIn("Nothing new or changed", out)
        self.assertIn(f"| already exported, unchanged | {exported} |", out)

    def test_due_pages_and_skipped_cards(self):
        out = run("due", "--market", "durham", "--as-of", "2026-11-22")
        self.assertIn("5 of 6 pages due", out)
        self.assertNotIn("county:37063|", out)                          # read yesterday, in full
        self.assertIn("6 of 6 pages due", run("due", "--market", "durham", "--as-of", "2026-11-22", "--all"))
        self.assertIn("county:37063|", run("due", "--market", "durham", "--as-of", "2026-12-01"))   # a week old
        # a reader told to skip cards over $5M and land-only cards still counts the page as read in full
        d = os.path.join(self.home, "runs", "2")
        lines = ("main|Kress Building|101 & 103 W Main St|Durham|NC|27701|$1,171,000|Retail, Office||4,574|||\n"
                 "TOTAL=3; LISTED=1; SKIPPED=2; SUGGESTED=20; NEXT=none\n")
        p = subprocess.run([sys.executable, os.path.join(REPO, "tools", "add_cards.py"), "--run-dir", d, "--market", "durham",
                            "--county", "37135", "--page-id", "county:37135", "--source", "x"], input=lines,
                           capture_output=True, text=True)
        self.assertIn("listed 1, skipped 2, suggested 20", p.stdout)
        out = run("ingest", "--market", "durham", "--run-dir", d, "--seen", "2026-11-22")
        self.assertIn("county:37135: 1 listed + 2 skipped of 3 shown, 1 page(s), complete", out)

    def test_deal_log_lists_every_deal_and_every_scan(self):
        run("build", "--market", "durham", "--out", os.path.join(self.home, "a.xlsx"), "--as-of", "2026-11-21")
        wb = load_workbook(os.path.join(self.home, "reports", "Deal Log.xlsx"))
        self.assertEqual(wb.sheetnames, ["Deals", "Scans"])
        head = [c.value for c in wb["Deals"][1]]
        deals = [dict(zip(head, [c.value for c in r])) for r in wb["Deals"].iter_rows(min_row=2)]
        self.assertEqual(len(deals), 26)                               # every listing analyzed, in or out of the box
        screens = {d["Screen"] for d in deals}
        self.assertIn("Out: land / pad site", screens)
        self.assertTrue(any(s.startswith("In buy box") for s in screens))
        star = next(d for d in deals if d["Listing"] == "4100 Durham-Chapel Hill Blvd")
        self.assertEqual(star["Exported"], "2026-11-21 (durham)")
        self.assertEqual(star["Markets"], "durham")
        events = [[c.value for c in r][2] for r in wb["Scans"].iter_rows(min_row=2)]
        self.assertEqual(events, ["ingest", "export"])
        # the floor format: a card-only listing first seen 11/21 shows 10+ on 12/1
        x = os.path.join(self.home, "full.xlsx")
        run("build", "--market", "durham", "--mode", "full", "--no-mark", "--out", x, "--as-of", "2026-12-01")
        head, rows, ws = rows_of(x, "All Properties")
        i = next(n for n, r in enumerate(rows, 2) if r["Listing"] == "4100 Durham-Chapel Hill Blvd")
        cell = ws.cell(i, head.index("Days on Market") + 1)
        self.assertEqual((cell.value, cell.number_format), (10, '0"+"'))
