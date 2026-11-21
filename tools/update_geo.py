#!/usr/bin/env python3
"""Rebuild data/geo from the Census Bureau's own files (no key). Run again when OMB issues new metro delineations.

Download the three files into an empty folder, then pass their paths:
  https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list1_2023.xlsx
  https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt
  https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.xlsx

  https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list2_2023.xlsx

  python tools/update_geo.py --delineation <list1_2023.xlsx> --zcta <tab20_zcta520_county20_natl.txt> \
      --ct <ct_cou_to_cousub_crosswalk.xlsx> --principal <list2_2023.xlsx> --out data/geo
"""
import argparse
import collections
import csv
import datetime
import json
import os
import re
import sys

from openpyxl import load_workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retail_scanner.geo import STATES, STATE_FIPS  # noqa: E402

MIN_SHARE = 0.05      # a ZIP "also reaches" a county only when that county holds at least 5% of the ZIP's land


def city_name(official):
    """'Nashville-Davidson metropolitan government (balance)' -> 'Nashville'; 'Indianapolis city (balance)' -> 'Indianapolis'."""
    name = str(official).strip()
    if "(balance)" in name:
        name = re.split(r"\s+city\b|-|/|\s+(?:metropolitan|unified|consolidated|urban)\b", name)[0]
    return name.strip()


def town(name):
    n = re.sub(r"\s+(town|city|borough)$", "", (name or "").strip().lower())
    return re.sub(r"[^a-z ]", "", n).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delineation", required=True)
    ap.add_argument("--zcta", required=True)
    ap.add_argument("--ct")
    ap.add_argument("--principal", help="Census list2 (principal cities)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    cbsa, counties = {}, {}
    ws = load_workbook(a.delineation, read_only=True).worksheets[0]
    title_row = None
    for row in ws.iter_rows(values_only=True):
        if row and row[0] == "CBSA Code":
            title_row = row
            continue
        if title_row is None or not row or not row[0] or not str(row[0]).isdigit():
            continue
        code, title, kind, county, state_name, sfips, cfips, central = (str(row[0]), row[3], row[4], row[7], row[8],
                                                                         str(row[9]).zfill(2), str(row[10]).zfill(3), row[11])
        cbsa[code] = {"title": title, "kind": "Metro" if kind.startswith("Metro") else "Micro"}
        counties[sfips + cfips] = {"name": county, "state": STATES.get(state_name, STATE_FIPS.get(sfips, "")),
                                   "cbsa": code, "central": central or ""}

    parts = collections.defaultdict(list)
    with open(a.zcta, encoding="utf-8-sig") as f:
        head = f.readline().rstrip("\n").split("|")
        iz, ic, iname, iland = (head.index("GEOID_ZCTA5_20"), head.index("GEOID_COUNTY_20"),
                                head.index("NAMELSAD_COUNTY_20"), head.index("AREALAND_PART"))
        for line in f:
            p = line.rstrip("\n").split("|")
            fips = p[ic]
            if fips and fips not in counties:
                counties[fips] = {"name": p[iname], "state": STATE_FIPS.get(fips[:2], ""), "cbsa": "", "central": ""}
            if p[iz]:
                parts[p[iz]].append((int(p[iland] or 0), fips))

    ct_rows = []
    if a.ct:
        ws = load_workbook(a.ct, read_only=True).worksheets[0]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or str(row[0]) != "09" or not row[3]:
                continue
            region = "09" + str(row[3]).zfill(3)
            counties.setdefault(region, {"name": row[4], "state": "CT", "cbsa": "", "central": ""})
            ct_rows.append({"town": town(row[8]), "region": region, "old_county": "09" + str(row[1]).zfill(3)})

    with open(os.path.join(a.out, "cbsa.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cbsa", "title", "kind"])
        for code in sorted(cbsa):
            w.writerow([code, cbsa[code]["title"], cbsa[code]["kind"]])
    with open(os.path.join(a.out, "counties.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fips", "name", "state", "cbsa", "central"])
        for fips in sorted(counties):
            c = counties[fips]
            w.writerow([fips, c["name"], c["state"], c["cbsa"], c["central"]])
    multi = 0
    with open(os.path.join(a.out, "zip_county.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["zip", "county", "others"])
        for z in sorted(parts):
            rows = sorted(parts[z], reverse=True)
            total = sum(r[0] for r in rows) or 1
            others = [fips for land, fips in rows[1:] if land / total >= MIN_SHARE]
            multi += bool(others)
            w.writerow([z, rows[0][1], ";".join(others)])
    if ct_rows:
        with open(os.path.join(a.out, "ct_towns.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["town", "region", "old_county"])
            w.writeheader()
            w.writerows(sorted(ct_rows, key=lambda r: r["town"]))
    principal = []
    if a.principal:
        ws = load_workbook(a.principal, read_only=True).worksheets[0]
        for row in ws.iter_rows(values_only=True):
            if row and row[0] and str(row[0]).isdigit() and row[3]:
                principal.append({"cbsa": str(row[0]), "city": city_name(row[3]), "official_name": row[3],
                                  "state": STATE_FIPS.get(str(row[4]).zfill(2), ""), "place_fips": str(row[4]).zfill(2) + str(row[5])})
        with open(os.path.join(a.out, "principal_cities.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["cbsa", "city", "official_name", "state", "place_fips"])
            w.writeheader()
            w.writerows(principal)
    meta = {
        "built": datetime.date.today().isoformat(),
        "sources": {
            "delineation": {"what": "OMB Bulletin 23-01 metro and micro delineations (July 2023), Census list1_2023.xlsx",
                            "url": "https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list1_2023.xlsx"},
            "zcta": {"what": "Census 2020 ZCTA5-to-county relationship file; a ZIP goes to the county holding most of its land",
                     "url": "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt"},
            "ct": {"what": "Census Connecticut county-to-planning-region crosswalk by town (CT replaced counties in 2022)",
                   "url": "https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.xlsx"},
            "principal": {"what": "OMB July 2023 principal cities of each metro and micro area, Census list2_2023.xlsx",
                          "url": "https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list2_2023.xlsx"},
        },
        "counts": {"cbsas": len(cbsa), "counties": len(counties), "zips": len(parts), "zips_in_2plus_counties": multi,
                   "ct_towns": len(ct_rows), "principal_cities": len(principal)},
        "note": "ZCTAs approximate USPS ZIP codes. PO-box-only ZIPs are not in the file; those listings show no MSA.",
    }
    with open(os.path.join(a.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    print(json.dumps(meta["counts"]))


if __name__ == "__main__":
    main()
