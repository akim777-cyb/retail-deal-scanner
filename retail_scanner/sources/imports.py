"""Import a spreadsheet of listings: an export from a service the firm is licensed to use, a broker's inventory list,
or a list Andrew keeps. Columns are matched by name (case and punctuation ignored); unknown columns are ignored.
"""
from __future__ import annotations
import csv
import os
import re

from ..listing import (acres, classify, clean, crexi_id, money, num, occupancy, pct, price_basis, sqft, year, zip5)

ALIASES = {
    "name": ["property name", "name", "building name", "listing name", "title", "property"],
    "address": ["address", "property address", "street address", "street", "address line 1", "location"],
    "city": ["city", "property city"], "state": ["state", "st", "property state"],
    "zip": ["zip", "zip code", "zipcode", "postal code", "property zip"],
    "price": ["price", "asking price", "list price", "for sale price", "sale price", "asking", "price usd"],
    "cap_rate": ["cap rate", "cap", "cap rate pct", "capitalization rate", "asking cap rate"],
    "noi": ["noi", "net operating income", "in place noi"],
    "sf": ["sf", "size", "building sf", "building size", "rba", "gla", "rentable building area", "square feet", "sq ft",
           "building size sf", "total sf", "gross leasable area"],
    "occupancy": ["occupancy", "leased", "pct leased", "percent leased", "occupancy pct", "percent occupied"],
    "tenants": ["tenants", "tenant", "anchor", "anchors", "anchor tenants", "major tenants", "tenancy detail"],
    "year_built": ["year built", "built", "yr built"],
    "lot_acres": ["lot size", "land area", "acres", "lot acres", "land area ac", "lot size acres"],
    "url": ["url", "link", "listing url", "listing link", "web link", "property url"],
    "types": ["property type", "type", "property types", "secondary type", "subtype", "property subtype"],
    "broker": ["broker", "listing broker", "agent", "listing agent", "sales contact"],
    "brokerage": ["brokerage", "listing company", "firm", "company", "broker company"],
    "days_on_market": ["days on market", "dom", "days on mkt"],
    "status": ["status", "listing status", "sale status"],
}


def _norm(h) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(h or "").lower())).strip()


def map_headers(headers: list[str]) -> dict:
    """{field: column index} for every field a header matches."""
    normed = [_norm(h) for h in headers]
    out = {}
    for field, names in ALIASES.items():
        for name in names:
            if name in normed:
                out[field] = normed.index(name)
                break
    return out


def read_table(path: str, sheet: str | None = None) -> list[list]:
    if path.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.reader(f)]


def load_file(path: str, source: str, sheet: str | None = None) -> tuple[list[dict], dict]:
    rows = read_table(path, sheet)
    head_i = next((i for i, r in enumerate(rows[:20]) if len(map_headers(r)) >= 3), None)
    if head_i is None:
        raise ValueError("no header row with at least three known columns (address, price, size ...) in the first 20 rows")
    cols = map_headers(rows[head_i])
    out = []
    for r in rows[head_i + 1:]:
        get = lambda f: r[cols[f]] if f in cols and cols[f] < len(r) else None  # noqa: E731
        address, name = clean(get("address")), clean(get("name"))
        if not (address or name):
            continue
        raw_price = get("price")
        x = {"name": name, "address": address, "city": clean(get("city")), "state": clean(get("state")).upper()[:2],
             "zip": zip5(get("zip")) or zip5(address), "price": money(raw_price), "price_basis": price_basis(raw_price) if not isinstance(raw_price, (int, float)) else "total",
             "cap_rate": pct(get("cap_rate")), "noi": money(get("noi")), "sf": sqft(get("sf")),
             "occupancy": occupancy(get("occupancy")) if get("occupancy") not in (None, "") else None,
             "year_built": year(get("year_built")), "lot_acres": acres(get("lot_acres")),
             "types": clean(get("types")) or "Retail", "status": clean(get("status")) or "Active",
             "broker": clean(get("broker")), "brokerage": clean(get("brokerage")),
             "sources": [source], "confirmed": False, "flags": [], "notes": []}
        dom = num(get("days_on_market"))
        if dom is not None:
            x["days_on_market"] = int(dom)
        tenants = [clean(t) for t in re.split(r"[;\n]", str(get("tenants") or "")) if clean(t)]
        if tenants:
            x["tenants"] = tenants
        url = clean(get("url"))
        if url.lower().startswith("http"):
            x["url"] = url
            if crexi_id(url):
                x["crexi_id"] = crexi_id(url)
        x["kind"], x["primary_type"], flags = classify(x["types"], name, "", x["sf"])
        x["flags"] += flags
        out.append(x)
    return out, {"file": os.path.basename(path), "header_row": head_i + 1, "columns": sorted(cols)}
