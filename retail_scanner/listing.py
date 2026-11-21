"""One listing = one dict. Parsing helpers, dedupe keys, type classification and merging reads."""
from __future__ import annotations
import re

_ABBR = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "boulevard": "blvd", "place": "pl", "drive": "dr",
    "court": "ct", "lane": "ln", "terrace": "ter", "parkway": "pkwy", "highway": "hwy", "hwy.": "hwy", "route": "rte",
    "rt": "rte", "north": "n", "south": "s", "east": "e", "west": "w", "northeast": "ne", "northwest": "nw",
    "southeast": "se", "southwest": "sw", "suite": "unit", "suites": "unit", "ste": "unit", "units": "unit",
    "apartment": "unit", "apt": "unit",
    "circle": "cir", "square": "sq", "trail": "trl", "pike": "pk", "turnpike": "tpke", "center": "ctr", "way": "wy",
}
_DIRS = {"n", "s", "e", "w", "ne", "nw", "se", "sw", "north", "south", "east", "west"}
_SUFFIX = {"st", "ave", "rd", "blvd", "pl", "dr", "ct", "ln", "ter", "pkwy", "hwy", "rte", "cir", "sq", "trl", "pk",
           "tpke", "ctr", "wy", "unit", "street", "avenue", "road", "drive", "lane", "highway", "parkway", "boulevard"}

# Fields that a listing-page read knows better than a results-page card. A later card never overwrites them.
DETAIL_FIELDS = {"kind", "subtype", "tenants", "tenant_count", "tenancy", "lease_type", "walt_years", "year_built",
                 "lot_acres", "broker", "brokerage", "listed_on", "days_on_market", "noi"}
# Fields the ledger owns. A read never writes them directly.
LEDGER_FIELDS = {"exports", "review", "price_history", "first_seen", "page_read_on", "page_read_price"}


def clean(s) -> str:
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()


_KEEP_CAPS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "US", "SR", "CR", "FM", "RR", "PO", "LLC"}


def tidy_caps(text: str) -> str:
    """'112 E MAIN ST' -> '112 E Main St'. Text that is not all capitals is left as written."""
    t = clean(text)
    if not t or not t.isupper():
        return t
    out = []
    for w in t.split(" "):
        core = re.sub(r"[^A-Z]", "", w)
        out.append(w if (re.search(r"\d", w) or core in _KEEP_CAPS) else w.capitalize())
    return " ".join(out)


def num(value):
    """The first number in a text, or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(value))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def price_basis(text) -> str:
    """'total', 'per_sf' (land or condo pricing), 'unpriced' or 'range'."""
    t = clean(text).lower()
    if not t or num(t) is None or any(w in t for w in ("unpriced", "call", "offers", "tbd", "n/a", "undisclosed")):
        return "unpriced"
    if re.search(r"/\s*(sf|sq|ft|acre|ac|mo|yr)|per\s+(sf|square|acre)|psf", t):
        return "per_sf"
    if re.search(r"\d\s*(-|–|to)\s*\$?\d", t):
        return "range"
    return "total"


def money(text):
    """A total dollar amount, or None (unpriced, per-SF or per-acre pricing)."""
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None
    t = clean(text).lower()
    if price_basis(t) in ("unpriced", "per_sf"):
        return None
    v = num(t)
    if v is None or v <= 0:
        return None
    if re.search(r"\d\s*(m|mm|million)\b", t) and v < 10000:
        v *= 1_000_000
    elif re.search(r"\d\s*k\b", t) and v < 100000:
        v *= 1000
    return v


def pct(value):
    """A cap rate as a fraction (8.25% -> 0.0825). None when blank, zero or implausible."""
    v = num(value)
    if v is None or v <= 0:
        return None
    if v >= 1:
        v = v / 100.0
    return v if v <= 0.25 else None


def occupancy(value):
    """Occupancy as a fraction from text like '100% Occupied', '12 of 14 units leased', 'Fully Leased' or 95."""
    if isinstance(value, (int, float)):
        v = float(value)
        v = v / 100 if v > 1 else v
        return v if 0 <= v <= 1 else None
    t = clean(value).lower()
    if not t:
        return None
    m = re.search(r"(\d+)\s*(?:of|/)\s*(\d+)\s*(?:units?|suites?|spaces?|tenants?)?\s*(?:are\s+)?(?:leased|occupied)", t)
    if m and int(m.group(2)) > 0:
        return min(int(m.group(1)) / int(m.group(2)), 1.0)
    if re.search(r"\bfully\s+(leased|occupied)|\b100\s*%\s*(leased|occupied|occupancy)", t):
        return 1.0
    m = (re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:leased|occupied|occupancy)", t)
         or re.search(r"(?:occupancy|leased|occupied)\s*(?:rate)?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%", t)
         or re.fullmatch(r"(\d+(?:\.\d+)?)\s*%?", t))
    if m:
        v = float(m.group(1)) / 100
        return v if 0 <= v <= 1 else None
    if re.fullmatch(r"(100%\s*)?vacant|vacant( building)?", t):
        return 0.0
    return None


def sqft(value):
    if isinstance(value, (int, float)):
        return float(value) if value >= 100 else None
    t = clean(value).lower()
    if not t or ("acre" in t and not re.search(r"\b(sf|sq|square)", t)):
        return None
    v = num(t)
    return v if v and v >= 100 else None


def acres(value):
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    t = clean(value).lower()
    v = num(t)
    if v is None or v <= 0:
        return None
    if re.search(r"\b(sf|sq\s*ft|square feet)\b", t):
        return round(v / 43560, 3)
    return v


def year(value):
    m = re.search(r"\b(18|19|20)\d{2}\b", str(value or ""))
    return int(m.group(0)) if m else None


def zip5(value) -> str:
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(value or ""))
    return m.group(1) if m else ""


def crexi_id(url) -> str:
    m = re.search(r"crexi\.com/properties/(\d+)", str(url or ""), re.I)
    return m.group(1) if m else ""


def _norm_address(address: str) -> str:
    a = clean(address).lower().replace("#", " unit ")
    a = re.sub(r"[.,;]", " ", a)
    a = re.sub(r"\s*&\s*", " & ", a)
    return " ".join(_ABBR.get(w, w) for w in a.split())


def addr_key(address, zip_code="", city="", state="") -> str:
    """A stable key so the same property read twice lands on one row."""
    a = _norm_address(address)
    if not a:
        return ""
    z = zip5(zip_code)
    return f"{a}|{z}" if z else f"{a}|{clean(city).lower()}|{clean(state).lower()}"


def match_key(address, zip_code) -> str:
    """A looser key: ZIP + first house number + street direction + first street word, for '2900-2924 Minnesota Ave SE'
    vs '2900 Minnesota Avenue SE'. The direction stays in: 112 W Main St and 112 E Main St are different buildings."""
    z = zip5(zip_code)
    a = _norm_address(address)
    m = re.match(r"(\d+)", a)
    if not z or not m:
        return ""
    rest = re.sub(r"^[\s\d,&\-–]+", " ", a[m.end():]).split()
    pre = rest[0] if rest and rest[0] in _DIRS else ""
    words = [re.sub(r"[^a-z0-9]", "", w) for w in rest if w not in _DIRS and w not in _SUFFIX and not w.isdigit() and w != "&"]
    words = [w for w in words if w]
    return f"{z}|{m.group(1)}|{pre}|{words[0] if words else ''}"


def unit_of(address) -> str:
    """'308 W Rosemary St, Suite 305' -> '305'; no unit -> ''."""
    m = re.search(r"\bunit\s*#?\s*([a-z0-9][a-z0-9-]*)", _norm_address(address))
    return m.group(1) if m else ""


def is_portfolio(x: dict) -> bool:
    return any(str(f).startswith("portfolio") for f in x.get("flags") or [])


def listing_key(x: dict) -> str:
    k = addr_key(x.get("address"), x.get("zip"), x.get("city"), x.get("state"))
    if k:
        return ("portfolio:" + k) if is_portfolio(x) else k
    if x.get("crexi_id"):
        return f"crexi:{x['crexi_id']}"
    return "name:" + "|".join(clean(x.get(f)).lower() for f in ("name", "city", "state"))


def name_tokens(name) -> set:
    stop = {"the", "for", "sale", "retail", "center", "plaza", "property", "building", "of", "and", "at", "in", "nnn", "a"}
    return {w for w in re.findall(r"[a-z0-9]+", clean(name).lower()) if w not in stop and len(w) > 1}


# ---- what kind of property is it ----------------------------------------------------------------
_MULTI = re.compile(r"multi[- ]?tenant|\b(\d+|two|three|four|five|six|seven|eight|nine|ten)[- ]tenant|\btenants\b|anchored|"
                    r"shadow[- ]anchor|units? leased|\bstrip\b|shopping cent|\bplaza\b|shoppes|\bshops\b|marketplace|"
                    r"\bcommons\b|\bcrossing\b|\bpromenade\b|\bgalleria\b|neighborhood center|community center|power center", re.I)
_NNN = re.compile(r"\bnnn\b|net lease|\babs(olute)?\.?\b|ground lease|single[- ]tenant|corporate[- ]guarant|franchisee|"
                  r"\b\d+[- ]?(yr|year)s?\b.{0,20}lease|lease.{0,20}\b\d+[- ]?(yr|year)", re.I)
_LAND = re.compile(r"\bland\b|\bacres?\b|\blot\b|\bpad\b|\bparcel\b|\boutparcel\b|\bsite\b|development|redevelopment|assemblage", re.I)
_BUSINESS = re.compile(r"\bbusiness\b(?!\s+(park|center|centre|district|plaza|campus|loop))", re.I)
_STREET = r"(?!\s+(pkwy|parkway|blvd|boulevard|dr|drive|rd|road|park|ave|avenue|way|st|street|ct|court|cir|circle|ln|lane|loop|hwy|plaza))"
_FLEX = re.compile(r"\bflex\b|\bindustrial\b" + _STREET + r"|manufacturing|distribution (center|facility|building)|"
                   r"self[- ]storage|warehouse\s*(building|space|/|&|and)\s*(office)?|office\s*/\s*warehouse", re.I)
_SPECIAL = re.compile(r"auto(motive)?\s*(body|sales|service|repair)|car\s*wash|\bdaycare\b|day\s*care|\bchurch\b|funeral|"
                      r"bowling|cinema|theater|theatre|\bhotel\b|\bmotel\b|gas station|c-store|convenience store|\bfuel\b", re.I)
_LOCATIONS = re.compile(r"\b(\d+)\s+locations\b", re.I)

RETAIL_TYPES = ("retail", "shopping center", "shopping centers", "strip center", "storefront", "storefronts", "restaurant",
                "net lease", "freestanding", "street retail", "shopping-centers")


def split_types(types_text) -> list[str]:
    return [clean(t) for t in re.split(r"[,/;•|]", str(types_text or "")) if clean(t)]


def classify(types_text, name="", tagline="", sf=None, subtype="") -> tuple[str, str, list[str]]:
    """Return (kind, primary type, flags). kind 'Land / Pad Site' and 'Business Sale' are outside any retail buy box."""
    types = split_types(types_text)
    primary = types[0] if types else ""
    words = " ".join(clean(x) for x in (name, tagline, subtype))
    flags = []
    m = _LOCATIONS.search(words)
    if m and int(m.group(1)) > 1:
        flags.append(f"portfolio ({m.group(1)} locations)")
    if re.search(r"sale\s*(or|/|&)\s*lease|lease\s*(or|/|&)\s*sale", words, re.I):
        flags.append("for sale or lease")
    if re.search(r"\bvacant\b|owner[- ]user|owner occup", words, re.I):
        flags.append("vacant or owner-user")
    if re.search(r"\bcondo\b|condominium", words, re.I):
        flags.append("condo unit")
    if re.search(r"ground lease", words, re.I):
        flags.append("ground lease")
    if _SPECIAL.search(words):
        flags.append("special-use building")
    lower = [t.lower() for t in types]
    if any(t in ("mixed use", "multifamily", "office", "industrial", "hospitality", "special purpose") for t in lower[1:]):
        flags.append("also tagged " + ", ".join(t for t in types[1:] if t.lower() != "retail"))
    if _BUSINESS.search(words) or any("business" in t for t in lower):
        return "Business Sale", primary, flags
    if lower and lower[0] == "land":
        return "Land / Pad Site", primary, flags
    if "land" in lower and (not sf or _LAND.search(words)) and not _MULTI.search(words):
        return "Land / Pad Site", primary, flags
    if lower and not any(lower[0] == t or lower[0].startswith(t) for t in RETAIL_TYPES):
        return primary or "Unknown", primary, flags
    if _FLEX.search(" ".join(clean(x) for x in (name, tagline, subtype))) and not _MULTI.search(words):
        return "Flex / Industrial", primary, flags
    sub = clean(subtype).lower()
    if any(w in sub for w in ("strip", "shopping", "neighborhood", "community", "power")) or _MULTI.search(words):
        kind = "Multi-Tenant Center"
    elif "net lease" in sub or "single tenant" in sub or _NNN.search(words):
        kind = "Single-Tenant NNN"
    elif any(t in ("mixed use", "multifamily", "office") for t in lower):
        kind = "Retail / Mixed Use"
    else:
        kind = "Retail Building"
    return kind, primary, flags


def is_active(listing: dict) -> bool:
    s = (listing.get("status") or "active").lower()
    return not any(w in s for w in ("pending", "sold", "off market", "inactive", "contract", "removed", "withdrawn", "closed"))


def merge(old: dict | None, new: dict, seen: str) -> dict:
    """Fold a newer read into the stored listing without losing confirmed facts. Keeps the price history."""
    if not old:
        out = {k: v for k, v in new.items() if k not in LEDGER_FIELDS}
        out["first_seen"] = seen
        out["last_seen"] = seen
        out["price_history"] = [[seen, new["price"]]] if new.get("price") else []
        return out
    out = dict(old)
    for k, v in new.items():
        if k in LEDGER_FIELDS:
            continue
        if k in ("flags", "notes", "sources", "pages", "markets"):
            out[k] = sorted(set(old.get(k) or []) | set(v or []))
        elif k == "confirmed":
            out[k] = bool(old.get(k)) or bool(v)
        elif k in DETAIL_FIELDS and old.get("confirmed") and not new.get("confirmed") and old.get(k) not in (None, "", []):
            continue
        elif k == "url" and old.get("url") and not v:
            continue
        elif v not in (None, "", []):
            out[k] = v
    if new.get("price") and new["price"] != old.get("price"):
        out["price_history"] = list(old.get("price_history") or []) + [[seen, new["price"]]]
    out["last_seen"] = max(seen, old.get("last_seen") or seen)
    return out
