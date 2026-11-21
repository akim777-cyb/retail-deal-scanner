"""Command line for the retail deal scanner. Run from the repo root:  python -m retail_scanner.cli <command> ...

  find-msa    look up a metro area by name or CBSA code
  new-market  write a market pack (its counties and the Crexi pages to read) for any MSA or list of counties
  ingest      add the cards and listing-page reads from a run folder to the market's ledger
  import      add listings from a spreadsheet (an export the firm is licensed to use, a broker list)
  build       screen the ledger and write the Excel; by default only listings new or changed since the last export
  todo        listings whose page should be opened next (First Pass first), with the search that finds each one
  mark        record a decision on a listing (pass, pursue, reviewed, dead, clear) so later exports leave it out
  stats       what the ledger holds for a market
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime
import glob
import json
import os

from . import workbook
from .geo import Geo, crexi_city_url, crexi_county_url
from .ledger import Ledger, change_since_export
from .listing import is_active, listing_key
from .screening import evaluate, locate
from .sources import cards, details, imports

ROOT = os.environ.get("RETAIL_SCANNER_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def today() -> str:
    return datetime.date.today().isoformat()


def paths(market_key: str) -> dict:
    return {"market": os.path.join(ROOT, "markets", f"{market_key}.json"),
            "ledger": os.path.join(ROOT, "data", "ledger", f"{market_key}.jsonl"),
            "coverage": os.path.join(ROOT, "data", "ledger", f"{market_key}.coverage.json"),
            "reports": os.path.join(ROOT, "reports", market_key)}


def load_market(key: str) -> dict:
    with open(paths(key)["market"], encoding="utf-8") as f:
        m = json.load(f)
    m["county_set"] = {c["fips"] for c in m["counties"]}
    return m


def load_profile(key: str) -> dict:
    with open(os.path.join(ROOT, "profiles", f"{key}.json"), encoding="utf-8") as f:
        return json.load(f)


def load_coverage(key: str) -> dict:
    p = paths(key)["coverage"]
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


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
        for c in geo.principal_cities(cbsa):
            pages.append({"id": f"city:{c['city']}, {c['state']}", "label": f"{c['city']}, {c['state']} (city page)",
                          "county": "", "url": crexi_city_url(c["state"], c["city"], a.type_path)})
    pack = {
        "key": a.key, "name": title, "as_of": today(), "cbsa": cbsa, "msa": geo.msa_label(cbsa) if cbsa else "",
        "counties": [{"fips": c["fips"], "name": c["name"], "state": c["state"], "central": c.get("central", "")}
                     for c in counties],
        "pages": pages, "page_size": 60,
        "notes": ["Read every county page, then the principal-city pages: Crexi's county and city pages do not list "
                  "the same listings (on 2026-11-21 the Durham city page showed 9 listings its county page did not). "
                  "The ledger merges the overlap. Each page also carries suggested listings from other areas, which "
                  "the scanner drops."],
    }
    os.makedirs(os.path.dirname(p["market"]), exist_ok=True)
    with open(p["market"], "w", encoding="utf-8") as f:
        json.dump(pack, f, indent=1)
    print(f"wrote markets/{a.key}.json: {title}; {len(counties)} counties; {len(pages)} pages to read")
    for pg in pages:
        print(f"  {pg['id']:<32} {pg['url']}")


# ---- reading listings in ------------------------------------------------------------------------
def _coverage_rows(run_dir: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(run_dir, "coverage_*.csv"))):
        with open(path, newline="", encoding="utf-8") as f:
            rows += list(csv.DictReader(f, delimiter="|"))
    return rows


def update_coverage(market_key: str, run_dir: str, seen: str, page_size: int) -> dict:
    """Coverage per market page (county:<fips> or city:<name>): what was read, against what the page said it holds."""
    cov = load_coverage(market_key)
    by_page = collections.defaultdict(list)
    for r in _coverage_rows(run_dir):
        by_page[r.get("page_id") or f"county:{r['county']}"].append(r)
    for page_id, rows in by_page.items():
        total = max((int(r["total"]) for r in rows if (r.get("total") or "").isdigit()), default=None)
        main = sum(int(r["main"] or 0) for r in rows)
        last_short = any(int(r["main"] or 0) < page_size for r in rows)
        cov[page_id] = {"date": seen, "total_shown": total, "main_cards_read": main, "pages_read": len(rows),
                        "complete": bool((total is not None and main >= total) or (total is None and last_short)),
                        "source": rows[0].get("source_url")}
    with open(paths(market_key)["coverage"], "w", encoding="utf-8") as f:
        json.dump(cov, f, indent=1, sort_keys=True)
    return cov


def cmd_ingest(a):
    market, geo = load_market(a.market), Geo()
    led = Ledger(paths(a.market)["ledger"])
    seen = a.seen or today()
    listings, dropped = cards.load_run(a.run_dir, market, geo)
    counts = collections.Counter(led.upsert(x, seen)[0] for x in listings)
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
            k = led.upsert(stub, seen)[1]
        led.items[k] = details.apply_detail(led.items[k], d)
        led.items[k]["last_seen"] = max(seen, led.items[k].get("last_seen") or seen)
        applied += 1
    led.save()
    cov = update_coverage(a.market, a.run_dir, seen, market.get("page_size", 60))
    print(f"cards kept: {len(listings)} ({dict(counts)}); dropped: {dropped or 'none'}")
    print(f"listing-page reads applied: {applied}" + (f"; not matched: {unmatched}" if unmatched else ""))
    print(f"ledger now holds {len(led.items)} listings")
    for page_id, c in sorted(cov.items()):
        if c["date"] == seen:
            print(f"  coverage {page_id}: {c['main_cards_read']} of {c['total_shown'] or '?'} shown, {c['pages_read']} page(s), "
                  f"{'complete' if c['complete'] else 'NOT complete'}")


def cmd_import(a):
    market, geo = load_market(a.market), Geo()
    led = Ledger(paths(a.market)["ledger"])
    rows, info = imports.load_file(a.file, a.source, a.sheet)
    counts, out = collections.Counter(), collections.Counter()
    for x in rows:
        inside, why = locate(x, market, geo)
        if not inside:
            out[why.split(" (")[0]] += 1
            continue
        counts[led.upsert(x, a.seen or today())[0]] += 1
    led.save()
    print(f"{info['file']}: header on row {info['header_row']}, columns matched: {', '.join(info['columns'])}")
    print(f"kept {sum(counts.values())} ({dict(counts)}); left out: {dict(out) or 'none'}; ledger now {len(led.items)}")


# ---- building the Excel ------------------------------------------------------------------------
def no_longer_listed(x: dict, coverage: dict) -> bool:
    """Gone when every page the listing was seen on has been read in full since, without it. Listings that came
    from an import or a link (no pages) stay until marked."""
    pages = x.get("pages") or []
    seen = x.get("last_seen") or ""
    return bool(pages) and all(coverage.get(p, {}).get("complete") and coverage[p]["date"] > seen for p in pages)


def build_rows(market_key: str, profile: dict, mode: str = "new"):
    market, geo = load_market(market_key), Geo()
    led = Ledger(paths(market_key)["ledger"])
    exp = profile.get("exports", {})
    coverage = load_coverage(market_key)
    counts = collections.Counter()
    out_reasons = collections.Counter()
    rows = []
    for x in led.items.values():
        if x.get("county_fips") not in market["county_set"]:
            counts["outside the market"] += 1
            continue
        if not is_active(x):
            counts["not active"] += 1
            continue
        if no_longer_listed(x, coverage):
            counts["no longer listed (gone from every page it was on)"] += 1
            continue
        r = evaluate(x, profile, geo)
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
    return market, led, chosen, first, counts, out_reasons


def market_pages(market: dict) -> list[dict]:
    """The pages a full read covers (market packs written before city pages existed list counties only)."""
    if market.get("pages"):
        return market["pages"]
    return [{"id": f"county:{c['fips']}", "label": f"{c['name']}, {c['state']}", "county": c["fips"],
             "url": crexi_county_url(c)} for c in market["counties"]]


def report_md(market, counts, out_reasons, coverage, first, mode, excel, rows) -> str:
    lines = [f"# {market['name']}: {today()} ({'new and changed only' if mode == 'new' else 'full'} export)", ""]
    lines += ["| Count | Listings |", "| --- | --- |"] + [f"| {k} | {v} |" for k, v in counts.items()]
    if out_reasons:
        lines += ["", "Outside the buy box, by reason: " + "; ".join(f"{k} {v}" for k, v in out_reasons.most_common())]
    lines += ["", "| Page | Read on | Listings read | Shown on the page | Complete |", "| --- | --- | --- | --- | --- |"]
    unread, partial = [], []
    for pg in market_pages(market):
        cv = coverage.get(pg["id"])
        if not cv:
            unread.append(pg["label"])
            lines.append(f"| {pg['label']} | not read | | | no |")
        else:
            lines.append(f"| {pg['label']} | {cv['date']} | {cv['main_cards_read']} | {cv['total_shown'] or 'not shown'} | "
                         f"{'yes' if cv['complete'] else 'no'} |")
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
    lines += ["", "**Not fetched:** " + ("; ".join(gaps) if gaps else "nothing; every county was read in full.")]
    if first:
        lines += ["", "| First Pass | Ask | Cap | UW Cap | DSCR | Change |", "| --- | --- | --- | --- | --- | --- |"]
        for r in first[:15]:
            lines.append(f"| {r['address']}, {r['city']} | ${r['price']:,.0f} | {(r['cap_rate'] or 0) * 100:.2f}% | "
                         f"{r['uw_cap'] * 100:.2f}% | {r['dscr']:.2f}x | {r['change']} |")
    if excel:
        lines += ["", f"Excel: `{excel}`"]
    return "\n".join(lines) + "\n"


def cmd_build(a):
    profile = load_profile(a.profile)
    market, led, rows, first, counts, out_reasons = build_rows(a.market, profile, a.mode)
    coverage = load_coverage(a.market)
    out = None
    if rows:
        os.makedirs(paths(a.market)["reports"], exist_ok=True)
        out = a.out or os.path.join(paths(a.market)["reports"],
                                    f"{market['name'].replace('/', '-')} {today()} ({'new' if a.mode == 'new' else 'full'}).xlsx")
        workbook.write(out, rows, first, profile, market)
        if not a.no_mark:
            led.mark_exported([r["key"] for r in rows], today(), a.mode)
            led.save()
    rel = os.path.relpath(out, ROOT) if out else None
    md = report_md(market, counts, out_reasons, coverage, first, a.mode, rel, rows)
    if not a.no_mark:
        os.makedirs(paths(a.market)["reports"], exist_ok=True)
        with open(os.path.join(paths(a.market)["reports"], f"{today()} run.md"), "a", encoding="utf-8") as f:
            f.write(md + "\n")
        with open(os.path.join(ROOT, "reports", "LAST_RUN.md"), "w", encoding="utf-8") as f:
            f.write(md)
    print(md if rows else md + "\nNothing new or changed since the last export: no Excel written.")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "first": [r["key"] for r in first], "counts": counts}, f, default=str)


def cmd_todo(a):
    profile = load_profile(a.profile)
    market, led, rows, first, counts, _ = build_rows(a.market, profile, "full")
    todo = [r for r in rows if not r["confirmed"] and (r["first_pass"] or (a.no_noi and r["noi"] is None))]
    todo.sort(key=lambda r: (not r["first_pass"], -(r["dscr"] or 0)))
    for r in todo[:a.top]:
        x = led.items[r["key"]]
        print(f"{r['address']}|{x.get('city')}|{x.get('state')}|{x.get('zip')}|"
              f"{'First Pass' if r['first_pass'] else 'no NOI'}|search: crexi {r['address']} {x.get('city')} {x.get('state')}")
    if not todo:
        print("nothing to open: every First Pass listing has had its page read")


def cmd_mark(a):
    led = Ledger(paths(a.market)["ledger"])
    hits = led.search(a.listing)
    if len(hits) != 1:
        print(f"{len(hits)} listings match {a.listing!r}; use the full address or the key:")
        for k in hits[:20]:
            print("  ", k, "|", led.items[k].get("name"))
        raise SystemExit(1)
    x = led.review(hits[0], a.status, a.note or "")
    led.save()
    print(f"{x.get('address')}, {x.get('city')}: {a.status}" + (f" ({a.note})" if a.note else ""))


def cmd_stats(a):
    led = Ledger(paths(a.market)["ledger"])
    xs = list(led.items.values())
    print("listings:", len(xs))
    print("by kind:", dict(collections.Counter(x.get("kind") for x in xs)))
    print("by source:", dict(collections.Counter(s for x in xs for s in x.get("sources", []))))
    print("listing page read:", sum(1 for x in xs if x.get("confirmed")))
    print("exported at least once:", sum(1 for x in xs if x.get("exports")))
    print("decisions:", dict(collections.Counter((x.get("review") or {}).get("status") for x in xs if x.get("review"))))
    cov = load_coverage(a.market)
    if cov:
        print("coverage:", {k: f"{v['main_cards_read']}/{v['total_shown']} on {v['date']}" for k, v in cov.items()})


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
    s.set_defaults(fn=cmd_new_market)
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
    s.add_argument("--out"); s.add_argument("--json"); s.set_defaults(fn=cmd_build)
    s = sub.add_parser("todo")
    s.add_argument("--market", required=True); s.add_argument("--profile", default="retail_pe")
    s.add_argument("--top", type=int, default=10); s.add_argument("--no-noi", action="store_true")
    s.set_defaults(fn=cmd_todo)
    s = sub.add_parser("mark")
    s.add_argument("--market", required=True); s.add_argument("--listing", required=True)
    s.add_argument("--status", required=True); s.add_argument("--note"); s.set_defaults(fn=cmd_mark)
    s = sub.add_parser("stats"); s.add_argument("--market", required=True); s.set_defaults(fn=cmd_stats)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
