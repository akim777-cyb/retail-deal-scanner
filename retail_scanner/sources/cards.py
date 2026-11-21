"""Listing cards read by Claude from public results pages (Crexi county pages by default).

tools/add_cards.py writes one pipe-separated file per helper in the run folder:
  market|helper|county|section|name|address|city|state|zip|price|types|cap_rate|sf|occupancy|tagline|listing_url|source_url|read_at
Only 'main' cards count. Crexi adds 'suggested' cards from other states under its results; they are dropped.
"""
from __future__ import annotations
import csv
import glob
import os
import re

from ..listing import (classify, clean, crexi_id, listing_key, money, occupancy, pct, price_basis, sqft, tidy_caps, year,
                       zip5)
from ..screening import locate

FIELDS = ["market", "helper", "county", "page_id", "section", "name", "address", "city", "state", "zip", "price", "types",
          "cap_rate", "sf", "occupancy", "tagline", "listing_url", "source_url", "read_at"]


def from_card(c: dict, market: dict, geo) -> tuple[dict | None, str]:
    """One card -> (listing, '') or (None, why it was dropped)."""
    if (c.get("section") or "main").strip().lower() != "main":
        return None, "suggested card from outside the search"
    name, tagline = clean(c.get("name")), clean(c.get("tagline"))
    address = tidy_caps(c.get("address"))
    if not (address or name):
        return None, "no address or name"
    raw_price = clean(c.get("price"))
    x = {
        "name": name, "address": address, "city": tidy_caps(c.get("city")),
        "state": clean(c.get("state")).upper()[:2], "zip": zip5(c.get("zip")) or zip5(address),
        "price": money(raw_price), "price_basis": price_basis(raw_price), "cap_rate": pct(c.get("cap_rate")),
        "sf": sqft(c.get("sf")), "types": clean(c.get("types")), "tagline": tagline,
        "status": "Active", "sources": ["crexi results page"], "confirmed": False, "flags": [], "notes": [],
    }
    page_id = clean(c.get("page_id")) or (f"county:{clean(c.get('county'))}" if clean(c.get("county")) else "")
    if page_id:
        x["pages"] = [page_id]
    url = clean(c.get("listing_url"))
    if url.lower().startswith("http"):
        x["url"], x["crexi_id"] = url, crexi_id(url)
    occ_text = clean(c.get("occupancy"))
    x["occupancy"] = occupancy(occ_text) if occ_text else None
    if x["occupancy"] is None:
        x["occupancy"] = occupancy(tagline) if re.search(r"leased|occupied", tagline, re.I) else None
    if occ_text and x["occupancy"] is None:
        x["notes"].append(f"occupancy on the card: {occ_text}")
    if x["cap_rate"] is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*cap\b|\bcap(?:\s*rate)?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%", f"{name} {tagline}", re.I)
        if m:
            x["cap_rate"] = pct(m.group(1) or m.group(2))
    built = re.search(r"\bbuilt\s+((18|19|20)\d{2})", tagline, re.I)
    if built:
        x["year_built"] = year(built.group(1))
    if x["price_basis"] == "per_sf":
        x["flags"].append(f"priced per square foot or acre ({raw_price}), not a total price")
    elif x["price_basis"] == "range":
        x["flags"].append(f"price shown as a range ({raw_price}); the first figure is used")
    x["kind"], x["primary_type"], flags = classify(x["types"], name, tagline, x["sf"])
    x["flags"] += flags
    # where is it: the ZIP decides; the county page it was read on is the fallback
    inside, why = locate(x, market, geo, hint=clean(c.get("county")))
    if not inside:
        return None, why
    if raw_price and x["price"] is None and x["price_basis"] == "unpriced":
        x["notes"].append(f"price on the card: {raw_price}")
    return x, ""


def read_cards(run_dir: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(run_dir, "cards_*.csv"))):
        with open(path, newline="", encoding="utf-8") as f:
            rows += list(csv.DictReader(f, delimiter="|"))
    return rows


def load_run(run_dir: str, market: dict, geo) -> tuple[list[dict], dict]:
    """Every main card in a run folder -> listings, plus counts of what was dropped and why."""
    out, dropped, seen = [], {}, {}
    for c in read_cards(run_dir):
        x, why = from_card(c, market, geo)
        if not x:
            dropped[why.split(" (")[0]] = dropped.get(why.split(" (")[0], 0) + 1
            continue
        sig = (x.get("crexi_id") or "", x["address"].lower(), x["zip"], x["name"].lower())
        if sig in seen:                      # the same card on two pages (county and city) or read twice:
            first = seen[sig]                # keep one row, remember every page it was on
            first["pages"] = sorted(set(first.get("pages") or []) | set(x.get("pages") or []))
            continue
        seen[sig] = x
        x["source_page"] = clean(c.get("source_url"))
        out.append(x)
    # two different listings that share one address on the same page stay two rows
    by_key = {}
    for x in out:
        by_key.setdefault((x["source_page"], listing_key(x)), []).append(x)
    for (_page, key), group in by_key.items():
        if len(group) > 1 and len({(g["name"].lower(), g.get("price")) for g in group}) > 1:
            for g in group:
                g["key"] = key + "|" + re.sub(r"[^a-z0-9]+", "-", g["name"].lower()).strip("-")
                g["key_locked"] = True
    return out, dropped
