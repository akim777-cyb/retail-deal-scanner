Retail Deal Scanner: Project Instructions (v2, 11/21/26)

1. What this Project is
The home of the Retail Deal Scanner: software that scans any metro (an MSA, or a list of counties) for every retail property listed for sale inside the buy box, screens each one in code, and returns a two-tab Excel (All Properties; First Pass) carrying only what is new or changed since the last export. Code, data and reports live in the private GitHub repo akim777-cyb/retail-deal-scanner. The retail-deal-hunt skill runs every scan. One listing Andrew pastes for an opinion goes to asset-analyzer, not a scan. Curbline deal work never runs here.

2. Who
Andrew (owner; New York). Not technical: any setup step is click by click, one step at a time.

3. Buy box (profiles/retail_pe.json; change it there, not here)
• Retail up to a $5,000,000 ask: multi-tenant centers, single-tenant net lease, retail buildings, retail-led mixed use.
• Out: land and pad sites, business-only sales, office / industrial / flex / hospitality-led listings, prices per SF or acre, unpriced listings over 75,000 SF.
• First Pass: DSCR of at least 1.25x on UW NOI at the profile's loan terms.
• UW NOI = listed NOI (else ask x listed cap, marked est.) less 5% vacancy and credit loss and $0.20/SF reserves. Loan: 65% LTV, 25-year amortization, 6.75% (Verify: placeholder until a lender quote). Target cap 8%.

4. Where the numbers come from
• Listings: public Crexi county pages and the city pages of the cities in the metro's name, read one page at a time; the listing page of each First Pass deal. Spreadsheet imports for lists the firm is licensed to use. LoopNet only as a single link Andrew sends (CoStar's terms prohibit scraping). No paid scrapers, no keys.
• MSA: Census files in data/geo (OMB July 2023 delineations, 2020 ZIP-to-county file, Connecticut town crosswalk, principal cities).
• Days on Market: the listing page, kept as a listed-on date so it stays current; "N+" = page not opened, at least N days since the scanner first saw it.
• All money math runs in retail_scanner/engine.py, never by hand.

5. The running log (no repeat work, no repeat exports)
• One ledger (data/ledger/deals.jsonl) for every market. A deal already in it is never analyzed, opened or exported again unless its price, status or listing page changed, or Andrew marks it.
• Exports carry only new or changed listings: price cut, newly priced, back on market, listing page read.
• "Pass", "pursue", "reviewed" or "dead" (the mark command) keeps a deal out of later exports unless its price drops 5% or more.
• reports/Deal Log.xlsx: every deal analyzed (Deals) and every scan (Scans), rebuilt after each export. Send it only when Andrew asks.

6. Credits
• Read only the pages `due` lists: never read, read in part, or last read more than 7 days ago. A page read for one market counts for every market.
• Read pages with the prompt `prompt` prints: it leaves out suggested cards, cards over the max price, and land-only or business-only cards.
• Never open a listing page already read at today's price; `todo` decides.
• 3 or more pages to read: helpers on Sonnet read and save them, up to 3 at a time. The main chat never retypes listings.
• Medium effort is enough for a scan. Aim for 5 to 10 minutes; say what was not read rather than run long.

7. The Excel (exact format)
• Two tabs: All Properties; First Pass.
• Columns, in order: Listing (address linked to the listing; a search link until its page is opened), Change, Property, City, State, MSA, Type, Ask, Days on Market, Cap Rate, NOI, Size (SF), Price / SF, Occupancy, Tenants, UW NOI, UW Cap, DSCR, Cash-on-Cash, Price at Target Cap, Lot (Acres), Year Built, Lease Type, WALT (Yrs), Broker, First Seen, Source.
• Flags sit in a note on the Listing cell. No other columns or tabs unless Andrew asks.

8. How to work in this Project
• Start every scan with the retail-deal-hunt skill: attach the repo with push access and run the tests first.
• Verdict first. Tables of seven columns or fewer in chat. Concise; no generic real estate education.
• Tag every figure Known (link and date), Estimate (logic shown) or Verify. Broker figures are Known as listed, not checked. N/A beats a guess.
• "Every listing" means every listing the pages read returned. Always say which pages were not read.
• Open the top 3 First Pass rows yourself before they go in an answer.
• Never go around a site that refuses a read; a failed page is a gap to report.
• Run the tests before and after any change; code changes go straight to main once they pass. Commit data/ and reports/ after every run.
• Price at Target Cap is internal: never in anything for a seller, broker or lender.
• Secrets: none are needed; never ask for, type or store a key or password. Claude never signs up, pays, accepts terms or publishes without Andrew's OK.

9. Sources of truth
The repo: code, buy box, market packs, ledger, page coverage, scan log and reports. README.md and docs/READING_GUIDE.md say how a scan runs. The newest Excel in reports/<market>/ and reports/Deal Log.xlsx.
