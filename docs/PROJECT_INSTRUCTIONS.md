What this Project is
The home of the Retail Deal Scanner: software that scans any metro (an MSA, or a list of counties) for every listed retail property inside the buy box and returns a two-tab Excel (All Properties; First Pass). The code lives in the private GitHub repo akim777-cyb/retail-deal-scanner; README.md and docs/READING_GUIDE.md say how a scan runs.

Buy box (profiles/retail_pe.json)
• Retail up to a $5,000,000 ask: multi-tenant centers, single-tenant net lease, retail buildings, retail-led mixed use.
• Out: land and pad sites, business-only sales, office / industrial / flex / hospitality-led listings, prices per SF or acre, unpriced listings over 75,000 SF.
• First Pass: DSCR of at least 1.25x on UW NOI at the profile's debt terms.
• UW NOI = listed NOI (else ask x listed cap, marked est.) less 5% vacancy and credit loss and $0.20/SF reserves. Loan: 65% LTV, 25-year amortization, 6.75% (placeholder until a lender quote). Target cap 8%. Change them in the profile, not here.

Where the numbers come from
• Listings: public Crexi county and principal-city pages, read by Claude one page at a time; listing pages for First Pass rows. Imports for lists the firm is licensed to use. LoopNet only as a single link Andrew sends.
• MSA: Census (OMB July 2023 delineations, 2020 ZIP-to-county file, Connecticut town crosswalk) in data/geo.
• All money math runs in retail_scanner/engine.py, never by hand.

How to work in this Project
• Verdict first. Tables of seven columns or fewer in chat. Concise.
• Tag every figure Known (link and date), Estimate (logic shown) or Verify. N/A beats a guess.
• Run the tests before and after any change; code changes go straight to main once they pass.
• Commit the ledger, coverage and reports after every run. An export carries only listings new or changed since the last one; "mark" records pass, pursue, reviewed or dead.
• "Every listing" means every listing the pages read returned. Always say which pages were not read.
• Open the top 3 First Pass rows yourself before they go in an answer.
• Never go around a site that refuses a read. A failed page is a gap to report.
• Price at Target Cap is internal: never in anything for a seller, broker or lender.
• Secrets: none are needed; never ask for, type or store a key or password.
