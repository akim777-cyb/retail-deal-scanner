# Reading pages: how Claude collects listings

Reads happen at a person's pace: one page at a time per helper, at most 3 helpers, no hidden data feeds, no paid
scrapers. If a site refuses a page, shows a CAPTCHA or asks to sign in, stop and log the page as not read.

## 1. Find each page

The market pack (`markets/<key>.json` -> `pages`) lists the Crexi county pages, then the principal-city pages. Read
them in that order: county pages first, then city pages.

- WebFetch only opens a page that already appeared in the chat. So first run a web search such as
  `crexi.com/properties/NC/Durham_County/Retail` and fetch the address the search returns. Crexi spells some
  addresses differently (on 2026-11-21 `.../NC/Orange_County` failed and `.../NC/Orange_county` worked). Use the spelling
  the search returns.
- If no search returns the Retail page, the county's all-types page (`.../NC/Person_County`) works as well, because
  the scanner drops non-retail listings itself.
- A page no search returns would need Andrew's one-click approval. If he is away, skip it, log it as not read, or
  read it in the built-in browser on the GEEKOM once he has allowed crexi.com there.
- Pages hold 60 listings. When `add_cards.py` says CONTINUE, read the next page (`?page=2`, ...), as given in the
  read's NEXT line.

## 2. Read a results page (WebFetch prompt, word for word)

```
This is a Crexi search results page. For EVERY property card on the page, output one line with exactly 13 pipe-separated fields, nothing else on the line:
section|name|street address|city|state|zip|asking price|property types|cap rate|building SF|occupancy or leased|tagline|listing link
- section: main for cards in the page's own results; suggested for cards under "Based off of your search, you may also like" or any other recommendation block.
- asking price exactly as shown (e.g. $2,116,000, Unpriced, $11/SF).
- listing link: the card's link target exactly as it appears in the page; empty if not visible.
- Replace any | inside a value with /. Leave any field empty when the card does not show it. Never guess.
After the lines write one line: TOTAL=<result count shown at the top>; CARDS=<cards you listed>; NEXT=<next results page link exactly as in the page, or none>.
```

Save it unchanged:

```
python tools/add_cards.py --run-dir runs/<date>/<market> --market <market> --county <FIPS> --page-id <page id> \
    --helper P1 --source "<the URL read>" --page 1 << 'EOF_CARDS'
<the lines>
EOF_CARDS
```

For a city page pass `--page-id "city:Durham, NC"` and `--county` with the county the city mostly sits in. The tool
repairs the usual slips (an extra empty field, the tagline in the link slot) and warns when main cards do not
match the page's count.

## 3. Read a listing page (WebFetch prompt, word for word)

Find the page with a web search (`crexi "<street address>" <city> <state>`). The search returns the listing address
(`https://www.crexi.com/properties/<id>/...`), and the row then links to it.

```
This is one Crexi listing page. Output exactly one line with 19 pipe-separated fields, then one NOTE line, nothing else:
status|property types|sub type|asking price|cap rate|NOI|building SF|lot acres|year built|occupancy|tenancy|number of tenants|tenant names|lease type|lease term remaining or WALT in years|broker name|brokerage|days on market or listed date|flags
- status: Active, Under Contract, Sold or Off Market, as the page shows (Active if it is simply for sale).
- tenant names: every tenant the page names, separated by semicolons.
- flags: semicolon-separated short notes for anything unusual (condo, ground lease, vacancy, value-add, auction, price drop, lease expirations within 2 years). Empty if none.
- Copy figures exactly as shown. Leave a field empty when the page does not show it. Never guess or compute.
NOTE: one short sentence on the most important fact for an investor (under 25 words).
```

```
python tools/add_details.py --run-dir runs/<date>/<market> --address "<street as on the card>" --zip <zip> \
    --city <city> --state <ST> --url "<listing URL>" --helper D1 << 'EOF_D'
<the line>
NOTE: <the note>
EOF_D
```

## 4. Then

`ingest`, `build`, open the Excel, check the top rows against their pages, commit `data/`, `markets/` and `reports/`.
