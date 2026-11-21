# Reading pages: how Claude collects listings

Reads happen at a person's pace: one page at a time per helper, at most 3 helpers, no hidden data feeds, no paid
scrapers. If a site refuses a page, shows a CAPTCHA or asks to sign in, stop and log the page as not read.

## 1. Find each page that is due

`python -m retail_scanner.cli due --market <key>` lists the pages to read now: never read, read only in part, or last
read more than 7 days ago (`--all` for a full refresh). A page read for any market counts for every market that
includes it. Read them in the order listed: county pages first, then the city pages of the cities in the metro's name.

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

## 2. Read a results page

Print the exact prompt (it carries the buy box's max price, so it never drifts from the profile):

```
python -m retail_scanner.cli prompt --kind results
```

Give it to WebFetch word for word. It lists only the cards that can matter, leaving out (and counting) suggested cards
from other areas, cards over the max price and cards whose first type is Land or Business for Sale. On the Durham
reads of 2026-11-21 that would have cut 165 card lines to 69 (58% fewer), and a page still counts as read in full.

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

## 3. Read a listing page

Only pages `todo` lists: a page already read at today's price is never opened again (it re-opens after a price change
or 90 days). Find the page with a web search (`crexi "<street address>" <city> <state>`): the search returns the
listing address (`https://www.crexi.com/properties/<id>/...`), and the row then links to it. Print the prompt with
`python -m retail_scanner.cli prompt --kind listing` and give it to WebFetch word for word.

```
python tools/add_details.py --run-dir runs/<date>/<market> --address "<street as on the card>" --zip <zip> \
    --city <city> --state <ST> --url "<listing URL>" --helper D1 << 'EOF_D'
<the line>
NOTE: <the note>
EOF_D
```

## 4. Who reads

Markets with 3 or more due pages: helpers on the Sonnet model read the pages and save them with `add_cards.py`, up to
3 at a time, one page at a time each. The main chat never retypes card lines; it only runs `ingest`, `build` and the
checks. One or two pages: read them in the main chat.

## 5. Then

`ingest`, `build`, open the Excel, check the top rows against their pages, commit `data/`, `markets/` and `reports/`.
`build` also rebuilds `reports/Deal Log.xlsx`.
