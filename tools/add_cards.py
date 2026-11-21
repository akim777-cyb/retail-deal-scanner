#!/usr/bin/env python3
"""Append the listing cards from one results page (read from stdin) to the run folder, and log page coverage.

Usage (the lines come from a WebFetch or browser read of one Crexi results page, pasted unchanged):
  python tools/add_cards.py --run-dir runs/2026-11-21/olympia --market olympia --county 53067 --helper P1 \
      --source "<results page URL>" --page 1 << 'EOF_CARDS'
  main|name|street address|city|state|zip|asking price|property types|cap rate|building SF|occupancy|tagline|listing link
  ...
  TOTAL=31; CARDS=51; NEXT=none
  EOF_CARDS

One card per line, 13 pipe-separated fields; the first is main or suggested. Unknown value = empty field.
"""
import argparse
import csv
import datetime
import os
import re
import sys

FIELDS = ["market", "helper", "county", "page_id", "section", "name", "address", "city", "state", "zip", "price", "types",
          "cap_rate", "sf", "occupancy", "tagline", "listing_url", "source_url", "read_at"]
COVERAGE = ["read_at", "page_id", "county", "source_url", "page", "total", "main", "suggested", "bad", "next"]


def split_line(line: str):
    """13 fields, repairing the slips a page reader makes: a missing last field, an extra empty field,
    or the tagline written into the link field."""
    line = line.strip()
    if line.startswith("|") and line.endswith("|") and line.count("|") > 13:
        line = line[1:-1]
    parts = [p.strip() for p in line.split("|")]
    if len(parts) == 12:
        parts.append("")                     # listing link left off entirely
    while len(parts) > 13 and parts[-1] == "":
        parts.pop()                          # trailing empty fields
    while len(parts) > 13:
        empties = [i for i in range(8, 12) if parts[i] == ""]
        if not empties:
            break
        parts.pop(empties[0])                # one empty field too many between types and link
    if len(parts) == 13 and parts[12] and not parts[12].lower().startswith("http") and not parts[11]:
        parts[11], parts[12] = parts[12], ""  # the tagline landed in the link field
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--market", required=True)
    ap.add_argument("--county", default="", help="county FIPS the page covers, e.g. 53067 (the fallback when a ZIP is unknown)")
    ap.add_argument("--page-id", default="", help="the page's id in the market pack, e.g. county:53067 or city:Olympia, WA")
    ap.add_argument("--helper", default="P1")
    ap.add_argument("--source", required=True)
    ap.add_argument("--page", default="1")
    ap.add_argument("--page-size", type=int, default=60)
    a = ap.parse_args()
    if not (a.county or a.page_id):
        ap.error("give --county or --page-id")
    page_id = a.page_id or f"county:{a.county}"
    os.makedirs(a.run_dir, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total, nxt, main_n, sugg_n, bad = "", "", 0, 0, 0
    rows = []
    for raw in sys.stdin.read().splitlines():
        line = raw.strip()
        if not line or set(line) <= set("|-: "):
            continue
        if line.upper().startswith("TOTAL="):
            m = re.search(r"TOTAL=\s*([\d,]+)", line, re.I)
            total = m.group(1).replace(",", "") if m else ""
            m = re.search(r"NEXT=\s*(\S+)", line, re.I)
            nxt = m.group(1).rstrip(";.") if m and m.group(1).lower() not in ("none", "none.", "none;") else ""
            continue
        parts = split_line(line)
        if parts and parts[0].lower() == "section":
            continue
        if len(parts) != 13 or parts[0].lower() not in ("main", "suggested"):
            bad += 1
            print(f"  BAD LINE (need 13 fields starting main or suggested; got {len(parts)}): {line[:120]}")
            continue
        section = parts[0].lower()
        main_n += section == "main"
        sugg_n += section == "suggested"
        rows.append(dict(zip(FIELDS, [a.market, a.helper, a.county, page_id, section] + parts[1:] + [a.source, now])))
    path = os.path.join(a.run_dir, f"cards_{a.helper}.csv")
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="|")
        if new_file:
            w.writeheader()
        w.writerows(rows)
    cov = os.path.join(a.run_dir, f"coverage_{a.helper}.csv")
    new_cov = not os.path.exists(cov)
    with open(cov, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="|")
        if new_cov:
            w.writerow(COVERAGE)
        w.writerow([now, page_id, a.county, a.source, a.page, total, main_n, sugg_n, bad, nxt])
    more = main_n >= a.page_size
    hint = f"CONTINUE: read the next page ({nxt or 'add ?page=N'})" if more else "LAST PAGE for this search"
    check = ""
    if total and not more and a.page == "1" and main_n != int(total):
        check = f" | CHECK: {main_n} main cards but the page shows {total} results"
    print(f"OK {a.helper} {page_id} page {a.page}: main {main_n}, suggested {sugg_n}, bad {bad}, total shown {total or '?'}"
          f" -> {hint}{check}")


if __name__ == "__main__":
    main()
