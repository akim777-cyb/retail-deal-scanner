# Retail Deal Scanner

Scans any metro (MSA) or list of counties for every listed retail property inside the buy box, runs a first-pass
underwriting in code, and writes a two-tab Excel: **All Properties** and **First Pass** (the ones that pencil at the
firm's debt terms). One ledger remembers every listing ever analyzed in every market, so a deal is read, opened and
exported once; **`reports/Deal Log.xlsx`** is the running log of every deal analyzed and every scan. A Claude chat
runs it through the `retail-deal-hunt` skill; setup steps for Andrew are in `docs/SETUP.md`.

**Buy box** (`profiles/retail_pe.json`): retail up to a $5,000,000 ask, covering multi-tenant centers, single-tenant net
lease, retail buildings and retail-led mixed use. Left out: land and pad sites, business-only sales,
office / industrial / flex / hospitality-led listings, prices per SF or acre, and unpriced listings over 75,000 SF.

## How a scan runs

1. **Market pack.** `new-market --key atlanta --msa "Atlanta"` writes the MSA's counties (Census) and the Crexi county
   and principal-city pages to read.
2. **Read the pages that are due.** `due` lists the pages never read, read only in part, or last read more than 7 days
   ago. Claude reads each public Crexi results page one at a time, the way a person would, with the exact prompt from
   `prompt` (`docs/READING_GUIDE.md`), and saves the cards with `tools/add_cards.py`. The prompt leaves out suggested
   cards, cards over the max price and land-only or business-only cards. A page that fails or is refused is logged as a
   gap, never worked around.
3. **Ingest.** `ingest` merges the cards into the ledger. The same listing on a county page and a city page, or on
   two runs, lands on one row; price changes are kept as history.
4. **Build.** `build` writes the Excel with only the listings that are new or changed since the last export (price cut,
   newly priced, back on the market, listing page read), plus a run report: counts, coverage by page, and what was not
   fetched.
5. **Open the First Pass listings.** `todo` lists them, skipping any page already read at today's price. Claude reads
   each listing page, saves it with `tools/add_details.py`, ingests and builds again. Those rows come back with tenants,
   NOI, days on market, lease type, broker and the real listing link.
6. **Decisions.** `mark --listing "<address>" --status pass` (or pursue, reviewed, dead) keeps a listing out of later
   exports unless its price drops 5% or more.

## Where each number comes from

| Figure | Source |
| --- | --- |
| Ask, cap rate, size, occupancy, tenants, lease type, broker | The listing as shown (results card, then the listing page). Broker figures, not checked. |
| Days on Market | The listing page, kept as a listed-on date so it stays current. "N+" = page not opened: at least N days since the scanner first saw it. |
| NOI | The listing page; else ask x listed cap rate, marked "est." |
| UW NOI, UW cap, DSCR, cash-on-cash, price at target cap | `retail_scanner/engine.py` with the assumptions in `profiles/retail_pe.json` |
| MSA | Census: OMB July 2023 delineations, the 2020 ZIP (ZCTA)-to-county file and the Connecticut town crosswalk (`data/geo/meta.json`) |

The debt rate in the profile is a placeholder (Verify) until the firm has a lender quote. Vacancy, reserves, LTV,
amortization, the 1.25x DSCR test and the 8% target cap are Estimates to replace with the firm's own terms.

## Sources and limits

- **Crexi public pages**, read by Claude at a person's pace. Crexi's Listing API only lets brokers send listings in;
  it offers no way to pull them out. Crexi's county and city pages do not list exactly the same listings, so a scan
  reads both and the ledger merges the overlap.
- **LoopNet is not read automatically.** CoStar's terms prohibit scraping and it has sued over automated access. A
  LoopNet link Andrew sends can be read as a single page (`tools/add_details.py`).
- **No paid scrapers** (Apify and the like). They go around Crexi's terms and bill per record.
- **Imports:** `import --file <xlsx or csv>` for any list the firm is licensed to use (a broker inventory, an
  export from a paid service the firm subscribes to).
- "Every listing" means every listing the pages read returned. Each run report names the pages not read.

## Commands (from the repo root)

```
pip install -r requirements.txt
python -m unittest discover -s tests
python -m retail_scanner.cli find-msa --query "Atlanta"
python -m retail_scanner.cli new-market --key atlanta --cbsa 12060
python -m retail_scanner.cli due --market atlanta                  # pages to read now
python -m retail_scanner.cli prompt --kind results                 # the exact page-read prompt
python tools/add_cards.py --run-dir runs/<date>/atlanta --market atlanta --county 13121 --page-id county:13121 --source "<page URL>" < cards.txt
python tools/add_details.py --run-dir runs/<date>/atlanta --address "<street>" --zip <zip> --url "<listing URL>" < page.txt
python -m retail_scanner.cli ingest --market atlanta --run-dir runs/<date>/atlanta
python -m retail_scanner.cli build --market atlanta                # new and changed only; --mode full for everything
python -m retail_scanner.cli todo --market atlanta                 # listing pages to open next (--in-box for all)
python -m retail_scanner.cli mark --listing "123 Main St" --status pass --note "why"
python -m retail_scanner.cli log                                   # rebuild reports/Deal Log.xlsx
python -m retail_scanner.cli import --market atlanta --file list.xlsx --source "broker inventory"
python -m retail_scanner.cli stats --market atlanta
```

## Layout

| Path | What it holds |
| --- | --- |
| `retail_scanner/engine.py` | All money math. Nothing else computes an NOI, a loan or a return. |
| `retail_scanner/listing.py` | Parsing, dedupe keys and property-type rules. |
| `retail_scanner/ledger.py` | The ledger: merge reads, price history, exports, decisions, what goes in the next export. |
| `retail_scanner/deallog.py` | The Deal Log workbook: every deal analyzed (Deals) and every scan (Scans). |
| `retail_scanner/geo.py` | ZIP -> county -> MSA from the Census files in `data/geo`. |
| `retail_scanner/screening.py` | One listing in, one Excel row out, with the buy-box check. |
| `retail_scanner/workbook.py` | The two tabs and their 27 columns. |
| `retail_scanner/sources/` | Results-page cards, listing-page reads, spreadsheet imports. |
| `tools/` | `add_cards.py`, `add_details.py` (save page reads), `update_geo.py` (rebuild `data/geo` from Census). |
| `profiles/` | Buy boxes and first-pass assumptions. |
| `markets/` | Market packs: counties and pages to read. |
| `data/ledger/deals.jsonl` | Every listing ever analyzed, in every market: price history, page reads, exports, decisions. |
| `data/coverage.json` | Every page read: when, how many listings, whether in full. Shared by all markets. |
| `data/scan_log.jsonl` | Every ingest and export, for the Deal Log's Scans tab. |
| `reports/<market>/` | Each export and run report. `reports/LAST_RUN.md` is the latest. |
| `reports/Deal Log.xlsx` | The running log, rebuilt after every export. |
| `tests/` | Run them before and after any change. |

## Rules

- Price at Target Cap is internal: never in anything for a seller, broker or lender.
- No keys, passwords or tokens in this repo, a chat or a log. The scanner needs none.
- Never go around a site that refuses a read. A failed page is a gap to report.
- Commit `data/` and `reports/` after every run: the ledger is what stops the next export from repeating this one.
- Credits: read only due pages; never open a listing page already read at today's price; page reads run in helpers on
  the Sonnet model so the main chat never retypes card lines.
