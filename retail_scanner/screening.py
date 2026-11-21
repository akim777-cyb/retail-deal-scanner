"""One listing in, one Excel row out: where it is, whether it is inside the buy box, and the first-pass math."""
from __future__ import annotations
from urllib.parse import quote_plus

from .engine import passes, underwrite
from .listing import is_active


def locate(x: dict, market: dict, geo, hint: str = "") -> tuple[bool, str]:
    """Set county_fips and cbsa on a listing. Returns (inside the market, why not)."""
    counties, flags = geo.counties_for(x.get("zip"), x.get("city"), x.get("state"))
    inside = [c for c in counties if c in market["county_set"]]
    if inside:
        x["county_fips"] = inside[0]
    elif not counties and hint in market["county_set"]:
        x["county_fips"] = hint
        flags = [f for f in flags if not f.startswith("ZIP not in")] + ["ZIP not in the Census file: county taken from the page it was read on"]
    else:
        return False, f"outside the market ({geo.county_name(counties[0]) if counties else 'county unknown'})"
    x["flags"] = sorted(set(x.get("flags") or []) | {f for f in flags if not f.startswith("ZIP also reaches")})
    x["cbsa"] = geo.cbsa_for(x["county_fips"])
    return True, ""


def buy_box(x: dict, profile: dict) -> list[str]:
    """Reasons a listing is outside the buy box. Empty = inside."""
    bb, why = profile["buy_box"], []
    if not is_active(x):
        why.append(f"status: {x.get('status')}")
    kind = x.get("kind") or ""
    if kind in bb.get("exclude_kinds", []):
        why.append(kind.lower())
    elif kind not in bb.get("include_kinds", []):
        why.append(f"not retail: {kind.lower() or 'type not shown'}")
    price = x.get("price")
    if x.get("price_basis") == "per_sf":
        why.append("priced per SF or acre")
    elif price is None:
        cap_sf = bb.get("unpriced_max_sf")
        if cap_sf and x.get("sf") and x["sf"] > cap_sf:
            why.append(f"unpriced and over {cap_sf:,} SF")
    else:
        if price > bb["max_price"]:
            why.append(f"ask over ${bb['max_price']:,.0f}")
        if price < bb.get("min_price", 0):
            why.append(f"ask under ${bb['min_price']:,.0f}")
    if bb.get("min_sf") and x.get("sf") and x["sf"] < bb["min_sf"]:
        why.append(f"under {bb['min_sf']:,} SF")
    return why


def search_link(x: dict) -> str:
    """Rows whose listing page has not been opened link to a search that lands on the listing."""
    q = " ".join(s for s in ("crexi", x.get("address") or x.get("name"), x.get("city"), x.get("state"), x.get("zip")) if s)
    return "https://www.google.com/search?q=" + quote_plus(q)


def evaluate(x: dict, profile: dict, geo) -> dict:
    uw = underwrite(x.get("price"), profile["underwriting"], noi=x.get("noi"), cap=x.get("cap_rate"), sf=x.get("sf"))
    reasons = buy_box(x, profile)
    in_box = not reasons
    ok, fails = passes(uw, x.get("occupancy"), profile["first_pass"])
    first = in_box and ok and x.get("price") is not None
    notes = list(x.get("flags") or []) + list(uw["notes"]) + list(x.get("notes") or [])
    if not x.get("confirmed"):
        notes.append("listing page not opened yet: tenants, NOI and lease terms not checked")
    if not x.get("url"):
        notes.append("the address link opens a search for the listing (the listing link has not been read yet)")
    if x.get("price") is None and x.get("price_basis") != "per_sf":
        notes.append("unpriced: ask the broker for price guidance")
    if in_box and not first and fails:
        notes.append("not on First Pass: " + "; ".join(fails))
    if len(x.get("price_history") or []) > 1:
        notes.append("price history: " + ", ".join(f"{d} ${p:,.0f}" for d, p in x["price_history"]))
    tenants = "; ".join(x.get("tenants") or [])
    if not tenants and (x.get("tenancy") or x.get("tenant_count")):
        tenants = f"{x.get('tenancy') or 'Tenants'}" + (f" ({x['tenant_count']})" if x.get("tenant_count") else "") + ": names not shown"
    broker = " / ".join(s for s in (x.get("broker"), x.get("brokerage")) if s)
    sources = x.get("sources") or []
    source = "; ".join(s[0].upper() + s[1:] for s in sources) if sources else ""
    cbsa = x.get("cbsa")
    msa = geo.msa_label(cbsa) if cbsa else ("Outside any metro area" if x.get("county_fips") else "")
    return {
        "key": x["key"], "address": x.get("address") or x.get("name"), "url": x.get("url") or search_link(x),
        "url_is_search": not x.get("url"), "name": x.get("name"), "city": x.get("city"), "state": x.get("state"),
        "zip": x.get("zip"), "msa": msa, "kind": x.get("kind"), "price": x.get("price"), "cap_rate": x.get("cap_rate"),
        "noi": x.get("noi") if x.get("noi") else uw["noi_basis"], "noi_est": not x.get("noi") and uw["noi_basis"] is not None,
        "sf": x.get("sf"), "price_psf": uw["price_psf"], "occupancy": x.get("occupancy"), "tenants": tenants,
        "uw_noi": uw["uw_noi"], "uw_cap": uw["uw_cap"], "dscr": uw["dscr"], "coc": uw["coc"],
        "price_at_target": uw["price_at_target"], "lot_acres": x.get("lot_acres"), "year_built": x.get("year_built"),
        "lease_type": x.get("lease_type"), "walt_years": x.get("walt_years"), "broker": broker,
        "days_on_market": x.get("days_on_market"), "first_seen": x.get("first_seen"), "source": source,
        "in_box": in_box, "reasons_out": reasons, "first_pass": first, "fails": fails, "notes": notes,
        "confirmed": bool(x.get("confirmed")), "status": x.get("status"), "change": "",
    }
