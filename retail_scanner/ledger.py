"""The deal ledger for one market: every listing ever seen, its price history, every export and every review.

One JSON line per listing in data/ledger/<market>.jsonl, sorted by key so Git diffs stay readable. The ledger is
what stops the scanner from exporting the same deal twice: an export only carries listings that are new, or that
changed since they were last exported (price cut, newly priced, back on the market, listing page read).
"""
from __future__ import annotations
import collections
import datetime
import json
import os
import re

from .listing import is_active, is_portfolio, listing_key, match_key, merge, name_tokens, unit_of

REVIEW_STATUSES = {"pass", "pursue", "reviewed", "dead"}


def today() -> str:
    return datetime.date.today().isoformat()


class Ledger:
    def __init__(self, path: str):
        self.path = path
        self.items: dict[str, dict] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        self.items[row["key"]] = row
        self._index()

    def _index(self):
        self.by_id = {x["crexi_id"]: k for k, x in self.items.items() if x.get("crexi_id")}
        self.by_match = collections.defaultdict(list)
        self.by_name = collections.defaultdict(list)
        for k, x in self.items.items():
            self._add_to_index(k, x)

    def _add_to_index(self, k: str, x: dict) -> None:
        mk = match_key(x.get("address"), x.get("zip"))
        if mk and k not in self.by_match[mk]:
            self.by_match[mk].append(k)
        nk = name_key(x)
        if nk and k not in self.by_name[nk]:
            self.by_name[nk].append(k)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            for key in sorted(self.items):
                f.write(json.dumps(self.items[key], ensure_ascii=False, sort_keys=True) + "\n")

    # ---- reading listings in -----------------------------------------------------------------
    def find(self, new: dict) -> str | None:
        """The stored key for this property, if it has been seen before under any spelling."""
        key = new.get("key") or listing_key(new)
        if key in self.items:
            return key
        if new.get("crexi_id") and new["crexi_id"] in self.by_id:
            return self.by_id[new["crexi_id"]]
        if new.get("key_locked"):            # two different listings shared an address on one page: no loose matching
            return None
        for k in self.by_name.get(name_key(new), []):   # same listing title in the same county, address written differently
            if prices_agree(self.items[k], new):
                return k
        for k in self.by_match.get(match_key(new.get("address"), new.get("zip")), []):
            if same_property(self.items[k], new):
                return k
        return None

    def upsert(self, new: dict, seen: str | None = None) -> tuple[str, str]:
        """Add or update one listing. Returns (what happened, key): 'new', 'updated' or 'price change'."""
        seen = seen or today()
        new = dict(new)
        new.setdefault("key", listing_key(new))
        found = self.find(new)
        old = self.items.get(found) if found else None
        if old:
            new["key"] = found
        merged = merge(old, new, seen)
        self.items[merged["key"]] = merged
        if merged.get("crexi_id"):
            self.by_id[merged["crexi_id"]] = merged["key"]
        self._add_to_index(merged["key"], merged)
        self._add_to_index(merged["key"], new)          # the spelling this read used, so the next read finds it too
        if not old:
            return "new", merged["key"]
        if new.get("price") and old.get("price") and new["price"] != old["price"]:
            return "price change", merged["key"]
        return "updated", merged["key"]

    # ---- exports and reviews -----------------------------------------------------------------
    def mark_exported(self, keys, date: str, mode: str, market: str = "") -> None:
        for k in keys:
            x = self.items[k]
            x.setdefault("exports", []).append({"date": date, "price": x.get("price"), "confirmed": bool(x.get("confirmed")),
                                                "status": x.get("status") or "Active", "mode": mode, "market": market})

    def review(self, key: str, status: str, note: str = "", date: str | None = None) -> dict:
        status = status.lower()
        if status not in REVIEW_STATUSES | {"clear"}:
            raise ValueError(f"status must be one of {sorted(REVIEW_STATUSES)} or clear")
        x = self.items[key]
        if status == "clear":
            x.pop("review", None)
        else:
            x["review"] = {"status": status, "date": date or today(), "price": x.get("price"), "note": note}
        return x

    def search(self, text: str) -> list[str]:
        t = (text or "").strip().lower()
        if not t:
            return []
        if t in self.items:
            return [t]
        return [k for k, x in self.items.items()
                if t in k or t == (x.get("crexi_id") or "") or t in (x.get("name") or "").lower()
                or t in (x.get("address") or "").lower()]


def name_key(x: dict) -> str:
    """County + listing title, for titles specific enough to name one property (two real words, or a street number)."""
    name = (x.get("name") or "").strip().lower()
    county = x.get("county_fips") or ""
    if not name or not county:
        return ""
    if len(name_tokens(name)) < 2 and not re.search(r"\d", name):
        return ""
    return county + "|" + " ".join(re.findall(r"[a-z0-9]+", name))


def prices_agree(a: dict, b: dict, tolerance: float = 0.25) -> bool:
    pa, pb = a.get("price"), b.get("price")
    return not (pa and pb) or abs(pa - pb) / max(pa, pb) <= tolerance


def same_property(a: dict, b: dict) -> bool:
    """Two reads with the same ZIP, house number, direction and street word: the same listing only when no fact
    disagrees. Real cases from 2026-11-21 that must stay apart: Suite 305 vs Suite 307 of one building; two
    listings at one address 38-41% apart in price."""
    if is_portfolio(a) != is_portfolio(b):
        return False
    if unit_of(a.get("address")) != unit_of(b.get("address")):
        return False
    if not prices_agree(a, b, 0.10):
        return False
    sa, sb = a.get("sf"), b.get("sf")
    if sa and sb and abs(sa - sb) / max(sa, sb) > 0.05:
        return False
    if (sa and sb) or (a.get("price") and b.get("price")):
        return True                          # size or price matches and nothing disagrees: titles often differ by source
    na, nb = name_tokens(a.get("name")), name_tokens(b.get("name"))
    if na and nb:
        return len(na & nb) / min(len(na), len(nb)) >= 0.5
    return True


def change_since_export(x: dict, resurface_drop: float = 0.05, include_raises: bool = False) -> tuple[str, bool]:
    """What changed since this listing was last exported or reviewed, and whether a 'new only' export carries it."""
    price = x.get("price")
    review = x.get("review") or {}
    if review.get("status") in REVIEW_STATUSES:
        ref = review.get("price")
        if price and ref and price <= ref * (1 - resurface_drop):
            return f"Price cut {(1 - price / ref) * 100:.0f}% since marked {review['status']} {review['date']}", True
        return f"Marked {review['status']} {review['date']}", False
    exports = x.get("exports") or []
    if not exports:
        return "New", True
    last = exports[-1]
    lp = last.get("price")
    if price and lp and price < lp:
        return f"Price cut from ${lp:,.0f} (exported {last['date']})", True
    if price and not lp:
        return f"Now priced (exported unpriced {last['date']})", True
    if not is_active({"status": last.get("status")}) and is_active(x):
        return f"Back on market (exported {last['date']})", True
    if x.get("confirmed") and not last.get("confirmed"):
        return f"Listing page read since export {last['date']}", True
    if price and lp and price > lp:
        return f"Price raised from ${lp:,.0f} (exported {last['date']})", include_raises
    return f"Exported {last['date']}" + (f" ({last['market']})" if last.get("market") else ""), False
