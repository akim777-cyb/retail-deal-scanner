"""Command line for the retail deal scanner. Run from the repo root:  python -m retail_scanner.cli <command> ...

  find-msa    look up a metro area by name or CBSA code
  new-market  write a market pack (its counties and the Crexi pages to read) for any MSA or list of counties
  due         the market's pages that need reading now: never read, read in part, or older than --days
  ingest      add the cards and listing-page reads from a run folder to the ledger
  import      add listings from a spreadsheet (an export the firm is licensed to use, a broker list)
  build       screen one market and write its Excel (new and changed only by default), run report and the Deal Log
  todo        listing pages worth opening next (First Pass first); pages already read at today's price are skipped
  mark        record a decision on a listing (pass, pursue, reviewed, dead, clear) so later exports leave it out
  log         rebuild reports/Deal Log.xlsx, the running log of every deal analyzed and every scan
  prompt      the exact WebFetch prompt for a results page or a listing page (max price from the profile)
  stats       what the ledger holds

One ledger (data/ledger/deals.jsonl) and one page-coverage file (data/coverage.json) serve every market, so a listing
seen in two markets is analyzed, opened and exported once, and a page read for one market counts for another.
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime
import glob
import json
import os

from . import deallog, workbook
from .geo import Geo, crexi_city_url, crexi_county_url
from .ledger import Ledger, change_since_export
from .listing import is_active, listing_key
from .screening import evaluate, locate
from .sources import cards, details, imports

ROOT = os.environ.get("RETAIL_SCANNER_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def today() -> str:
    return datetime.date.today().isoformat()


def paths(market_key: str = "") -> dict:
    return {"market": os.path.join(ROOT, "markets", f"{market_key}.json"),
            "ledger": os.path.join(ROOT, "data", "ledger", "deals.jsonl"),
            "coverage": os.path.join(ROOT, "data", "coverage.json"),
            "scan_log": os.path.join(ROOT, "data", "scan_log.jsonl"),
            "reports": os.path.join(ROOT, "reports", market_key),
            "deal_log": os.path.join(ROOT, "reports", "Deal Log.xlsx")}


def load_market(key: str) -> dict:
    with open(paths(key)["market"], encoding="utf-8") as f:
        m = json.load(f)
    m["county_set"] = {c["fips"] for c in m["counties"]}
    return m


def load_profile(key: str) -> dict:
    with open(os.path.join(ROOT, "profiles", f"{key}.json"), encoding="utf-8") as f:
        return json.load(f)


def load_coverage() -> dict:
    p = paths()["coverage"]
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_coverage(cov: dict) -> None:
    os.makedirs(os.path.dirname(paths()["coverage"]), exist_ok=True)
    with open(paths()["coverage"], "w", encoding="utf-8") as f:
        json.dump(cov, f, indent=1, sort_keys=True)


def log_event(event: dict) -> None:
    os.makedirs(os.path.dirname(paths()["scan_log"]), exist_ok=True)
    with open(paths()["scan_log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def read_events() -> list[dict]:
    p = paths()["scan_log"]
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def market_pages(market: dict) -> list[dict]:
    if market.get("pages"):
        return market["pages"]
    return [{"id": f"county:{c['fips']}", "label": f"{c['name']}, {c['state']}", "county": c["fips"],
             "url": crexi_county_url(c)} for c in market["counties"]]


def no_longer_listed(x: dict, coverage: dict) -> bool:
    """Gone when every page the listing was seen on has been read in full since, without it. Listings from an import
    or a link (no pages) stay until marked."""
    pages = x.get("pages") or []
    seen = x.get("last_seen") or ""
    return bool(pages) and all(coverage.get(p, {}).get("complete") and coverage[p]["date"] > seen for p in pages)


# ---- markets -----------------------------------------------------------------------------------
def cmd_find_msa(a):
    hits = Geo().find_cbsa(a.query)
    for code, title, kind in hits[:25]:
        print(f"{code}  {title}  ({kind})")
    if not hits:
        print("no metro or micro area matches", repr(a.query))


def cmd_new_market(a):
    geo = Geo()
    p = paths(a.key)
    if os.path.exists(p["market"]) and not a.force:
        raise SystemExit(f"markets/{a.key}.json exists (use --force to replace)")
    cbsa, title = "", a.name
    if a.counties:
        counties = []
        for text in a.counties:
            c = geo.find_county(text)
            if not c:
                raise SystemExit(f"county not found: {text!r} (write it as 'Durham County, NC')")
            counties.append(c)
    else:
        hits = geo.find_cbsa(a.cbsa or a.msa or "")
        if not hits:
            raise SystemExit("no metro area matches; try find-msa")
        if len(hits) > 1 and not (a.cbsa or "").isdigit():
            exact = [h for h in hits if h[1].lower().startswith((a.msa or "").lower())]
            if len(exact) != 1:
                print("several metro areas match; pass --cbsa with one code:")
                for h in hits[:15]:
                    print(f"  {h[0]}  {h[1]} ({h[2]})")
                raise SystemExit(1)
            hits = exact
        cbsa, title = hits[0][0], a.name or hits[0][1]
        counties = sorted(geo.counties_in(cbsa), key=lambda c: (c["central"] != "Central", c["name"]))
    pages = [{"id": f"county:{c['fips']}", "label": f"{c['name']}, {c['state']}", "county": c["fips"],
              "url": crexi_county_url(c, a.type_path)} for c in counties]
    if cbsa and not a.no_cities:
        cities = geo.principal_cities(cbsa)
        named = [c for c in cities if c["city"].lower() in geo.cbsa[cbsa]["title"].lower()]
        for c in (cities if a.all_cities else (named or cities[:1])):
            pages.append({"id": f"city:{c['city']}, {c['state']}", "label": f"{c['city']}, {c['state']} (city page)",
                          "county": "", "url": crexi_city_url(c["state"], c["city"], a.type_path)})
    pack = {
        "key": a.key, "name": title, "as_of": today(), "cbsa": cbsa, "msa": geo.msa_label(cbsa) if cbsa else "",
        "counties": [{"fips": c["fips"], "name": c["name"], "state": c["state"], "central": c.get("central", "")}
                     for c in counties],
        "pages": pages, "page_size": 60,
        "notes": ["Read every county page, then the city pages of the cities named in the metro's title: Crexi's county "
                  "and city pages do not list the same listings (on 2026-11-21 the Durham city page showed 9 listings its "
                  "county page did not). The ledger merges the overlap."],
    }
    os.makedirs(os.path.dirname(p["market"]), exist_ok=True)
    with open(p["market"], "w", encoding="utf-8") as f:
        json.dump(pack, f, indent=1)
    print(f"wrote markets/{a.key}.json: {title}; {len(counties)} counties; {len(pages)} pages to read")
    for pg in pages:
        print(f"  {pg['id']:<32} {pg['url']}")


def cmd_due(a):
    market, cov = load_market(a.market), load_coverage()
    day = datetime.date.fromisoformat(a.as_of) if a.as_of else datetime.date.today()
    cutoff = (day - datetime.timedelta(days=a.days)).isoformat()
    pages, due = market_pages(market), []
    for pg in pages:
        c = cov.get(pg["id"])
        if not c:
            why = "never read"
        elif not c["complete"]:
            why = f"read only in part on {c['date']}"
        elif c["date"] < cutoff:
            why = f"last read {c['date']}"
        elif a.all:
            why = f"read {c['date']} (full refresh asked)"
        else:
            continue
        due.append((pg, why))
    for pg, why in due:
        print(f"{pg['id']}|{pg['county']}|{pg['url']}|{why}")
    print(f"{len(due)} of {len(pages)} pages due" + ("" if due else f": every page was read in full in the last {a.days} days"))


# ---- reading listings in ------------------------------------------------------------------------
def _coverage_rows(run_dir: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(run_dir, "coverage_*.csv"))):
        with open(path, newline="", encoding="utf-8") as f:
            rows += list(csv.DictReader(f, delimiter="|"))
    return rows


def update_coverage(run_dir: str, seen: str, page_size: int) -> dict:
    """Coverage per page (county:<fips> or city:<name>), shared by every market: what was read against what the page
    said it holds. Skipped cards (over the max price, land, business sales) count as read."""
    cov = load_coverage()
    by_page = collections.defaultdict(list)
    for r in _coverage_rows(run_dir):
        by_page[r.get("page_id") or f"county:{r['county']}"].append(r)
    for page_id, rows in by_page.items():
        total = max((int(r["total"]) for r in rows if (r.get("total") or "").isdigit()), default=None)
        listed = sum(int(r.get("main") or 0) for r in rows)
        skipped = sum(int(r.get("skipped") or 0) for r in rows)
        last_short = any(int(r.get("main") or 0) + int(r.get("skipped") or 0) < page_size for r in rows)
        cov[page_id] = {"date": seen, "total_shown": total, "main_cards_read": listed, "skipped": skipped,
                        "pages_read": len(rows), "source": rows[0].get("source_url"),
                        "complete": bool((total is not None and listed + skipped >= total) or (total is None and last_short))}
    save_coverage(cov)
    return {k: v for k, v in cov.items() if k in by_page}


def cmd_ingest(a):
    market, geo = load_market(a.market), Geo()
    led = Ledger(paths()["ledger"])
    seen = a.seen or today()
    listings, dropped = cards.load_run(a.run_dir, market, geo)
    counts = collections.Counter()
    for x in listings:
        x["markets"] = [a.market]
        counts[led.upsert(x, seen)[0]] += 1
    applied, unmatched = 0, []
    for d in details.read_details(a.run_dir):
        probe = {"address": d.get("address"), "zip": d.get("zip"), "name": d.get("name") or "",
                 "city": d.get("city") or "", "state": d.get("state") or ""}
        probe["key"] = listing_key(probe)
        k = led.find(probe)
        if not k:
            stub = details.stub_from_detail(d)
            inside, why = locate(stub, market, geo)
            if not inside:
                unmatched.append(f"{d.get('address')} ({why})")
                continue
            stub["markets"] = [a.market]
            k = led.upsert(stub, seen)[1]
        led.items[k] = details.apply_detail(led.items[k], d)
        led.items[k]["last_seen"] = max(seen, led.items[k].get("last_seen") or seen)
        applied += 1
    led.save()
    cov = update_coverage(a.run_dir, seen, market.get("page_size", 60))
    log_event({"date": seen, "market": a.market, "event": "ingest", "pages": sorted(cov), "cards": len(listings),
               "new": counts["new"], "price_changes": counts["price change"], "pages_opened": applied})
    print(f"cards kept: {len(listings)} ({dict(counts)}); dropped: {dropped or 'none'}")
    print(f"listing-page reads applied: {applied}" + (f"; not matched: {unmatched}" if unmatched else ""))
    print(f"ledger now holds {len(led.items)} listings")
    for page_id, c in sorted(cov.items()):
        print(f"  coverage {page_id}: {c['main_cards_read']} listed + {c['skipped']} skipped of {c['total_shown'] or '?'} "
              f"shown, {c['pages_read']} page(s), {'complete' if c['complete'] else 'NOT complete'}")


def cmd_import(a):
    market, geo = load_market(a.market), Geo()
    led = Ledger(paths()["ledger"])
    seen = a.seen or today()
    rows, info = imports.load_file(a.file, a.source, a.sheet)
    counts, out = collections.Counter(), collections.Counter()
    for x in rows:
        inside, why = locate(x, market, geo)
        if not inside:
            out[why.split(" (")[0]] += 1
            continue
        x["markets"] = [a.market]
        if x.get("days_on_market") is not None:
            x["listed_on"] = (datetime.date.fromisoformat(seen) - datetime.timedelta(days=x.pop("days_on_market"))).isoformat()
        counts[led.upsert(x, seen)[0]] += 1
    led.save()
    log_event({"date": seen, "market": a.market, "event": "import", "pages": [info["file"]],
               "cards": sum(counts.values()), "new": counts["new"], "price_changes": counts["price change"]})
    print(f"{info['file']}: header on row {info['header_row']}, columns matched: {', '.join(info['columns'])}")
    print(f"kept {sum(counts.values())} ({dict(counts)}); left out: {dict(out) or 'none'}; ledger now {len(led.items)}")


# ---- building the Excel ------------------------------------------------------------------------
def build_rows(market_key: str, profile: dict, mode: str = "new", as_of: str | None = None):
    as_of = as_of or today()
    market, geo = load_market(market_key), Geo()
    led = Ledger(paths()["ledger"])
    coverage = load_coverage()
    exp = profile.get("exports", {})
    counts, out_reasons, rows = collections.Counter(), collections.Counter(), []
    for x in led.items.values():
        if x.get("county_fips") not in market["county_set"]:
            continue
        if not is_active(x):
            counts["not active"] += 1
            continue
        if no_longer_listed(x, coverage):
            counts["no longer listed (gone from every page it was on)"] += 1
            continue
        r = evaluate(x, profile, geo, as_of)
        if not r["in_box"]:
            counts["outside the buy box"] += 1
            for why in r["reasons_out"]:
                out_reasons[why] += 1
            continue
        r["change"], r["include"] = change_since_export(x, exp.get("resurface_price_drop", 0.05),
                                                        exp.get("include_price_raises", False))
        rows.append(r)
    rows.sort(key=lambda r: (not r["first_pass"], r["dscr"] is None, -(r["dscr"] or 0), r["price"] or 9e12))
    counts["in the buy box"] = len(rows)
    counts["first pass"] = sum(r["first_pass"] for r in rows)
    counts["new or changed since the last export"] = sum(r["include"] for r in rows)
    counts["already exported, unchanged"] = sum(1 for r in rows if not r["include"] and r["change"].startswith("Exported"))
    counts["marked pass / pursue / reviewed / dead"] = sum(1 for r in rows if r["change"].startswith("Marked"))
    chosen = [r for r in rows if r["include"]] if mode == "new" else rows
    first = [r for r in chosen if r["first_pass"]]
    return market, led, chosen, first, counts, out_reasons, coverage


def report_md(market, counts, out_reasons, coverage, first, mode, excel, rows, as_of) -> str:
    lines = [f"# {market['name']}: {as_of} ({'new and changed only' if mode == 'new' else 'full'} export)", ""]
    lines += ["| Count | Listings |", "| --- | --- |"] + [f"| {k} | {v} |" for k, v in counts.items()]
    if out_reasons:
        lines += ["", "Outside the buy box, by reason: " + "; ".join(f"{k} {v}" for k, v in out_reasons.most_common())]
    lines += ["", "| Page | Read on | Listings read | Skipped | Shown on the page | Complete |",
              "| --- | --- | --- | --- | --- | --- |"]
    unread, partial = [], []
    for pg in market_pages(market):
        cv = coverage.get(pg["id"])
        if not cv:
            unread.append(pg["label"])
            lines.append(f"| {pg['label']} | not read | | | | no |")
            continue
        lines.append(f"| {pg['label']} | {cv['date']} | {cv['main_cards_read']} | {cv.get('skipped', 0)} | "
                     f"{cv['total_shown'] or 'not shown'} | {'yes' if cv['complete'] else 'no'} |")
        if not cv["complete"]:
            partial.append(pg["label"])
    gaps = []
    if unread:
        gaps.append("pages not read: " + "; ".join(unread))
    if partial:
        gaps.append("pages read only in part: " + "; ".join(partial))
    no_noi = sum(1 for r in rows if r["noi"] is None)
    if no_noi:
        gaps.append(f"{no_noi} listings in this export show no NOI or cap rate (First Pass not run on them)")
    unopened = sum(1 for r in first if not r["confirmed"])
    if unopened:
        gaps.append(f"{unopened} First Pass listings not opened yet (tenants and lease terms unchecked)")
    lines += ["", "**Not fetched:** " + ("; ".join(gaps) if gaps else "nothing; every page was read in full.")]
    if first:
        lines += ["", "| First Pass | Ask | Days on Market | Cap | UW Cap | DSCR | Change |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in first[:15]:
            dom = "" if r["days_on_market"] is None else f"{r['days_on_market']}{'+' if r['dom_floor'] else ''}"
            lines.append(f"| {r['address']}, {r['city']} | ${r['price']:,.0f} | {dom} | {(r['cap_rate'] or 0) * 100:.2f}% | "
                         f"{r['uw_cap'] * 100:.2f}% | {r['dscr']:.2f}x | {r['change']} |")
    if excel:
        lines += ["", f"Excel: `{excel}`"]
    return "\n".join(lines) + "\n"


def write_deal_log(profile: dict, as_of: str | None = None) -> tuple[str, int]:
    led, geo, coverage = Ledger(paths()["ledger"]), Geo(), load_coverage()
    path = paths()["deal_log"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = deallog.write(path, led, profile, geo, lambda x: no_longer_listed(x, coverage), read_events(), as_of)
    return path, n


def cmd_build(a):
    profile, as_of = load_profile(a.profile), a.as_of or today()
    market, led, rows, first, counts, out_reasons, coverage = build_rows(a.market, profile, a.mode, as_of)
    out = None
    if rows:
        os.makedirs(paths(a.market)["reports"], exist_ok=True)
        out = a.out or os.path.join(paths(a.market)["reports"],
                                    f"{market['name'].replace('/', '-')} {as_of} ({'new' if a.mode == 'new' else 'full'}).xlsx")
        workbook.write(out, rows, first, profile, market)
        if not a.no_mark:
            led.mark_exported([r["key"] for r in rows], as_of, a.mode, a.market)
            led.save()
    rel = os.path.relpath(out, ROOT) if out else None
    md = report_md(market, counts, out_reasons, coverage, first, a.mode, rel, rows, as_of)
    if not a.no_mark:
        os.makedirs(paths(a.market)["reports"], exist_ok=True)
        with open(os.path.join(paths(a.market)["reports"], f"{as_of} run.md"), "a", encoding="utf-8") as f:
            f.write(md + "\n")
        with open(os.path.join(ROOT, "reports", "LAST_RUN.md"), "w", encoding="utf-8") as f:
            f.write(md)
        log_event({"date": as_of, "market": a.market, "event": "export", "rows": len(rows), "first_pass": len(first),
                   "file": rel or "nothing new: no file"})
        path, n = write_deal_log(profile, as_of)
        md += f"\nDeal Log: `{os.path.relpath(path, ROOT)}` ({n} listings analyzed in all markets)\n"
    print(md if rows else md + "\nNothing new or changed since the last export: no Excel written.")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "first": [r["key"] for r in first], "counts": counts}, f, default=str)


def cmd_todo(a):
    profile, as_of = load_profile(a.profile), a.as_of or today()
    market, led, rows, first, counts, _, _ = build_rows(a.market, profile, "full", as_of)
    picks = []
    for r in rows:
        x = led.items[r["key"]]
        if not details.needs_page_read(x, as_of):
            continue
        if r["first_pass"]:
            picks.append((0, "First Pass", r, x))
        elif a.no_noi and r["noi"] is None:
            picks.append((1, "no NOI or cap shown", r, x))
        elif a.in_box:
            picks.append((2, "in buy box", r, x))
    picks.sort(key=lambda p: (p[0], -(p[2]["dscr"] or 0), p[2]["price"] or 9e12))
    for _, why, r, x in picks[:a.top]:
        print(f"{x.get('address')}|{x.get('city')}|{x.get('state')}|{x.get('zip')}|{why}|"
              f"search: crexi \"{x.get('address')}\" {x.get('city')} {x.get('state')}")
    print(f"{min(len(picks), a.top)} of {len(picks)} listing pages worth opening"
          + ("" if picks else ": every one that matters has been read at its current price"))


RESULTS_PROMPT = """This is a Crexi search results page. List the property cards in the page's own results, one per line, with exactly 13 pipe-separated fields, nothing else on the line:
main|name|street address|city|state|zip|asking price|property types|cap rate|building SF|occupancy or leased|tagline|listing link
- Leave out, and only count: cards under "Based off of your search, you may also like" or any other recommendation block (SUGGESTED); cards whose asking price is above {max_price}, or whose first property type is Land or Business for Sale (SKIPPED). Keep every other card, Unpriced ones included.
- asking price exactly as shown (e.g. $2,116,000, Unpriced, $11/SF).
- listing link: the card's link target exactly as it appears in the page; empty if not visible.
- Replace any | inside a value with /. Leave any field empty when the card does not show it. Never guess.
After the lines write one line: TOTAL=<result count shown at the top>; LISTED=<cards listed>; SKIPPED=<cards left out by the price or type rule>; SUGGESTED=<recommendation cards left out>; NEXT=<next results page link exactly as in the page, or none>."""

LISTING_PROMPT = """This is one Crexi listing page. Output exactly one line with 19 pipe-separated fields, then one NOTE line, nothing else:
status|property types|sub type|asking price|cap rate|NOI|building SF|lot acres|year built|occupancy|tenancy|number of tenants|tenant names|lease type|lease term remaining or WALT in years|broker name|brokerage|days on market or listed date|flags
- status: Active, Under Contract, Sold or Off Market, as the page shows (Active if it is simply for sale).
- tenant names: every tenant the page names, separated by semicolons.
- flags: semicolon-separated short notes for anything unusual (condo, ground lease, vacancy, value-add, auction, price drop, lease expirations within 2 years). Empty if none.
- Copy figures exactly as shown. Leave a field empty when the page does not show it. Never guess or compute.
NOTE: one short sentence on the most important fact for an investor (under 25 words)."""


def cmd_prompt(a):
    """The exact WebFetch prompt for a page read, with the buy box's max price filled in."""
    if a.kind == "listing":
        print(LISTING_PROMPT)
    else:
        print(RESULTS_PROMPT.format(max_price=f"${load_profile(a.profile)['buy_box']['max_price']:,.0f}"))


def cmd_mark(a):
    led = Ledger(paths()["ledger"])
    hits = led.search(a.listing)
    if len(hits) != 1:
        print(f"{len(hits)} listings match {a.listing!r}; use the full address or the key:")
        for k in hits[:20]:
            print("  ", k, "|", led.items[k].get("name"))
        raise SystemExit(1)
    x = led.review(hits[0], a.status, a.note or "")
    led.save()
    print(f"{x.get('address')}, {x.get('city')}: {a.status}" + (f" ({a.note})" if a.note else ""))


def cmd_log(a):
    path, n = write_deal_log(load_profile(a.profile), a.as_of)
    print(f"wrote {os.path.relpath(path, ROOT)}: {n} listings analyzed; {len(read_events())} scan events")


def cmd_stats(a):
    led = Ledger(paths()["ledger"])
    xs = list(led.items.values())
    if a.market:
        xs = [x for x in xs if a.market in (x.get("markets") or [])]
    print("listings:", len(xs))
    print("by market:", dict(collections.Counter(m for x in xs for m in x.get("markets") or ["(none)"])))
    print("by kind:", dict(collections.Counter(x.get("kind") for x in xs)))
    print("listing page read:", sum(1 for x in xs if x.get("confirmed")))
    print("exported at least once:", sum(1 for x in xs if x.get("exports")))
    print("decisions:", dict(collections.Counter((x.get("review") or {}).get("status") for x in xs if x.get("review"))))
    print("pages read:", len(load_coverage()), "| scan events:", len(read_events()))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="retail_scanner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("find-msa"); s.add_argument("--query", required=True); s.set_defaults(fn=cmd_find_msa)
    s = sub.add_parser("new-market")
    s.add_argument("--key", required=True, help="short file name, e.g. atlanta")
    s.add_argument("--cbsa", help="CBSA code, e.g. 12060"); s.add_argument("--msa", help="metro name, e.g. 'Atlanta'")
    s.add_argument("--counties", nargs="+", help="instead of an MSA: 'Durham County, NC' 'Orange County, NC'")
    s.add_argument("--name"); s.add_argument("--type-path", default="Retail"); s.add_argument("--force", action="store_true")
    s.add_argument("--no-cities", action="store_true", help="county pages only")
    s.add_argument("--all-cities", action="store_true", help="every principal city, not just the ones in the metro's name")
    s.set_defaults(fn=cmd_new_market)
    s = sub.add_parser("due")
    s.add_argument("--market", required=True); s.add_argument("--days", type=int, default=7)
    s.add_argument("--all", action="store_true", help="every page, for a full refresh"); s.add_argument("--as-of")
    s.set_defaults(fn=cmd_due)
    s = sub.add_parser("ingest")
    s.add_argument("--market", required=True); s.add_argument("--run-dir", required=True); s.add_argument("--seen")
    s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("import")
    s.add_argument("--market", required=True); s.add_argument("--file", required=True)
    s.add_argument("--source", required=True, help="what the file is, e.g. 'broker inventory list'")
    s.add_argument("--sheet"); s.add_argument("--seen"); s.set_defaults(fn=cmd_import)
    s = sub.add_parser("build")
    s.add_argument("--market", required=True); s.add_argument("--profile", default="retail_pe")
    s.add_argument("--mode", choices=["new", "full"], default="new")
    s.add_argument("--no-mark", action="store_true", help="preview: do not record this export in the ledger")
    s.add_argument("--as-of"); s.add_argument("--out"); s.add_argument("--json"); s.set_defaults(fn=cmd_build)
    s = sub.add_parser("todo")
    s.add_argument("--market", required=True); s.add_argument("--profile", default="retail_pe")
    s.add_argument("--top", type=int, default=10); s.add_argument("--as-of")
    s.add_argument("--no-noi", action="store_true", help="also in-box listings with no NOI or cap shown")
    s.add_argument("--in-box", action="store_true", help="also every other in-box listing (fills days on market)")
    s.set_defaults(fn=cmd_todo)
    s = sub.add_parser("mark")
    s.add_argument("--market", help="not needed: one ledger serves every market"); s.add_argument("--listing", required=True)
    s.add_argument("--status", required=True); s.add_argument("--note"); s.set_defaults(fn=cmd_mark)
    s = sub.add_parser("log"); s.add_argument("--profile", default="retail_pe"); s.add_argument("--as-of")
    s.set_defaults(fn=cmd_log)
    s = sub.add_parser("prompt"); s.add_argument("--kind", choices=["results", "listing"], default="results")
    s.add_argument("--profile", default="retail_pe"); s.set_defaults(fn=cmd_prompt)
    s = sub.add_parser("stats"); s.add_argument("--market"); s.set_defaults(fn=cmd_stats)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
