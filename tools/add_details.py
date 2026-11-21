#!/usr/bin/env python3
"""Save one listing-page read (Crexi, or a broker or LoopNet page Andrew sent) to the run folder.

Usage (the line comes from a WebFetch or browser read of the listing page, pasted unchanged):
  python tools/add_details.py --run-dir runs/2026-11-21/olympia --address "4100 Durham-Chapel Hill Blvd" --zip 27707 \
      --city Durham --state NC --url "<listing page URL>" --helper D1 << 'EOF_D'
  status|types|subtype|price|cap_rate|noi|sf|lot_acres|year_built|occupancy|tenancy|tenant_count|tenants|lease_type|walt|broker|brokerage|listed|flags
  NOTE: <one short remark>
  EOF_D
"""
import argparse
import csv
import datetime
import os
import sys

try:
    import fcntl
except ImportError:          # Windows: helpers write one at a time there
    fcntl = None

FIELDS = ["name", "address", "city", "state", "zip", "listing_url", "helper", "status", "types", "subtype", "price",
          "cap_rate", "noi", "sf", "lot_acres", "year_built", "occupancy", "tenancy", "tenant_count", "tenants",
          "lease_type", "walt", "broker", "brokerage", "listed", "flags", "note", "read_at"]
PAGE = FIELDS[7:26]          # the 19 fields read from the page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--address", required=True)
    ap.add_argument("--zip", default="")
    ap.add_argument("--city", default="")
    ap.add_argument("--state", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--url", required=True)
    ap.add_argument("--helper", default="D1")
    a = ap.parse_args()
    lines = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    data = [l for l in lines if not l.upper().startswith("NOTE:")]
    note = " ".join(l[5:].strip() for l in lines if l.upper().startswith("NOTE:"))[:300].replace("|", "/")
    if not data:
        print("BAD: no data line")
        sys.exit(1)
    line = data[0][1:-1] if data[0].startswith("|") and data[0].endswith("|") else data[0]
    parts = [p.strip() for p in line.split("|")]
    if len(parts) == len(PAGE) - 1:
        parts.append("")             # flags field left off entirely
    if len(parts) != len(PAGE):
        print(f"BAD: need {len(PAGE)} fields, got {len(parts)}: {data[0][:160]}")
        sys.exit(1)
    row = dict(zip(PAGE, parts))
    row.update(name=a.name, address=a.address, city=a.city, state=a.state, zip=a.zip, listing_url=a.url.strip(),
               helper=a.helper, note=note, read_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    os.makedirs(a.run_dir, exist_ok=True)
    path = os.path.join(a.run_dir, "details.csv")
    with open(path, "a", newline="", encoding="utf-8") as f:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX)
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="|")
        if f.tell() == 0:
            w.writeheader()
        w.writerow(row)
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_UN)
    print(f"OK saved {a.address}: {row['status'] or '?'} | {row['price'] or 'no price'} | cap {row['cap_rate'] or '-'} | "
          f"NOI {row['noi'] or '-'} | {row['sf'] or '?'} SF | occ {row['occupancy'] or '-'} | tenants {row['tenants'] or '-'}")


if __name__ == "__main__":
    main()
