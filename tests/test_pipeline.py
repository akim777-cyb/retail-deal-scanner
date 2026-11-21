"""End to end in a scratch folder: market pack -> page reads -> ledger -> Excel -> re-export only what changed."""
import contextlib
import io
import json
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
        self.assertIn("main 26, suggested 20, bad 0, total shown 26 -> LAST PAGE", out)
        run("ingest", "--market", "durham", "--run-dir", d, "--seen", "2026-11-21")

    def test_durham_read_to_excel_and_only_changes_after(self):
        self.durham()
        ledger = [json.loads(l) for l in read(os.path.join(self.home, "data", "ledger", "durham.jsonl")).splitlines()]
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
                            "3950 Linden Ave", "--zip", "45432", "--url", "https://www.crexi.com/properties/123456/ohio-3950-linden"],
                           input=page, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        run("ingest", "--market", "dayton", "--run-dir", d, "--seen", "2026-11-22")
        x2 = os.path.join(self.home, "dayton2.xlsx")
        run("build", "--market", "dayton", "--out", x2)
        head, rows, ws = rows_of(x2, "First Pass")
        r = rows[0]
        self.assertTrue(r["Change"].startswith("Listing page read since export"))
        self.assertEqual(r["Tenants"], "Dollar General; Subway; H&R Block")
        self.assertEqual(r["Type"], "Multi-Tenant Center")
        self.assertEqual(r["NOI"], 117_150)
        self.assertEqual(ws["A2"].hyperlink.target, "https://www.crexi.com/properties/123456/ohio-3950-linden")
        self.assertEqual(r["Broker"], "Jane Doe / Example Realty")
        self.assertEqual(r["WALT (Yrs)"], 4.2)
        self.assertEqual(r["Days on Market"], 45)


if __name__ == "__main__":
    unittest.main()
