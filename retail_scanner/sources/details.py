"""Listing-page reads (Crexi, or a broker or LoopNet page Andrew sends), saved by tools/add_details.py:
  name|address|city|state|zip|listing_url|helper|status|types|subtype|price|cap_rate|noi|sf|lot_acres|year_built|
  occupancy|tenancy|tenant_count|tenants|lease_type|walt|broker|brokerage|listed|flags|note|read_at
"""
from __future__ import annotations
import csv
import datetime
import os
import re

from ..listing import (acres, addr_key, classify, clean, crexi_id, money, num, occupancy, pct, sqft, year, zip5)

FIELDS = ["name", "address", "city", "state", "zip", "listing_url", "helper", "status", "types", "subtype", "price",
          "cap_rate", "noi", "sf", "lot_acres", "year_built", "occupancy", "tenancy", "tenant_count", "tenants",
          "lease_type", "walt", "broker", "brokerage", "listed", "flags", "note", "read_at"]


def read_details(run_dir: str) -> list[dict]:
    path = os.path.join(run_dir, "details.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="|"))


def detail_key(d: dict) -> str:
    return addr_key(d.get("address"), d.get("zip"))


def apply_detail(listing: dict, d: dict) -> dict:
    """Fold one listing-page read into a listing. The page beats the results card on every field it shows."""
    out = dict(listing)
    url = clean(d.get("listing_url"))
    if url.lower().startswith("http"):
        out["url"] = url
        if crexi_id(url):
            out["crexi_id"] = crexi_id(url)
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower() if url else ""
    host = {"crexi.com": "crexi", "loopnet.com": "LoopNet"}.get(host, host or "the")
    flags = [f.strip() for f in (d.get("flags") or "").split(";") if f.strip()]
    for field in ("name", "city", "state"):
        if clean(d.get(field)) and not out.get(field):
            out[field] = clean(d[field]).upper()[:2] if field == "state" else clean(d[field])
    for field, fn in (("price", money), ("cap_rate", pct), ("noi", money), ("sf", sqft), ("lot_acres", acres),
                      ("year_built", year), ("occupancy", occupancy)):
        v = fn(d.get(field)) if clean(d.get(field)) else None
        if v is not None:
            out[field] = v
    walt = clean(d.get("walt"))
    if walt:
        if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}|\b(19|20)\d{2}\b", walt):
            out["notes"] = sorted(set(out.get("notes") or []) | {f"lease term on the page: {walt} (a date, not a WALT)"})
        elif num(walt) is not None and num(walt) < 100:
            out["walt_years"] = num(walt)
    tc = num(d.get("tenant_count"))
    if tc:
        out["tenant_count"] = int(tc)
    tenants = [clean(t) for t in re.split(r";", d.get("tenants") or "") if clean(t)]
    if tenants:
        out["tenants"] = tenants
    for field, dst in (("tenancy", "tenancy"), ("lease_type", "lease_type"), ("broker", "broker"),
                       ("brokerage", "brokerage"), ("subtype", "subtype")):
        if clean(d.get(field)):
            out[dst] = clean(d[field])
    read_on = (clean(d.get("read_at")) or datetime.date.today().isoformat())[:10]
    listed = clean(d.get("listed"))
    if listed:
        dom = re.search(r"(\d+)\s*days?", listed, re.I)
        when = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", listed) or re.search(r"(\d{4})-(\d{2})-(\d{2})", listed)
        if dom:
            out["listed_on"] = (datetime.date.fromisoformat(read_on) - datetime.timedelta(days=int(dom.group(1)))).isoformat()
        elif when:
            a, b, c = (int(g) for g in when.groups())
            y, m, dd = (a, b, c) if a > 31 else (c + 2000 if c < 100 else c, a, b)
            try:
                out["listed_on"] = datetime.date(y, m, dd).isoformat()
            except ValueError:
                pass
        out.pop("days_on_market", None)
    out["page_read_on"] = read_on
    if clean(d.get("types")):
        out["types"] = clean(d["types"])
    if clean(d.get("status")):
        out["status"] = clean(d["status"])
    kind, primary, cflags = classify(out.get("types"), out.get("name"), out.get("tagline"), out.get("sf"), out.get("subtype"))
    multi = re.search(r"multi", out.get("tenancy") or "", re.I) or (out.get("tenant_count") or 0) >= 2
    if multi and kind in ("Retail Building", "Single-Tenant NNN"):
        kind = "Multi-Tenant Center"
    out["kind"], out["primary_type"] = kind, primary
    if d.get("note"):
        out["notes"] = sorted(set(out.get("notes") or []) | {clean(d["note"])})
    out["flags"] = sorted(set(out.get("flags") or []) | set(flags) | set(cflags))
    out["sources"] = sorted(set(out.get("sources") or []) | {f"{host} listing page"})
    out["confirmed"] = True
    out["page_read_price"] = out.get("price")
    return out


def needs_page_read(x: dict, as_of: str, max_age_days: int = 90) -> bool:
    """Open a listing page only when it has never been read, its price moved since the read, or the read is old."""
    if not x.get("confirmed") or not x.get("page_read_on"):
        return True
    if x.get("price") != x.get("page_read_price"):
        return True
    age = (datetime.date.fromisoformat(as_of) - datetime.date.fromisoformat(x["page_read_on"])).days
    return age > max_age_days


def stub_from_detail(d: dict) -> dict:
    """A listing known only from its page (a link Andrew sent), with no results card."""
    return {"address": clean(d.get("address")), "zip": zip5(d.get("zip")), "name": clean(d.get("name")),
            "city": clean(d.get("city")), "state": clean(d.get("state")).upper()[:2],
            "status": "Active", "sources": [], "flags": [], "notes": [], "confirmed": False}
