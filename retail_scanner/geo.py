"""Where a listing is: ZIP -> county -> metro area (MSA), from the Census Bureau's own files in data/geo.

Sources (see data/geo/meta.json and tools/update_geo.py):
  - OMB July 2023 metro and micro delineations (Census list1_2023.xlsx): county -> CBSA.
  - Census 2020 ZCTA-to-county relationship file: ZIP -> county (the county with the most of the ZIP's land).
  - Census Connecticut crosswalk: town -> planning region (CT's county equivalents since 2022).
"""
from __future__ import annotations
import csv
import json
import os
import re

GEO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "geo")

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY", "Puerto Rico": "PR",
}
STATE_FIPS = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
              "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
              "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
              "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
              "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
              "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY", "72": "PR"}


def _town(name: str) -> str:
    n = re.sub(r"\s+(town|city|borough)$", "", (name or "").strip().lower())
    return re.sub(r"[^a-z ]", "", n).strip()


class Geo:
    def __init__(self, folder: str = GEO_DIR):
        self.folder = folder
        self.cbsa, self.county, self.zip, self.ct_town, self.ct_old = {}, {}, {}, {}, {}
        with open(os.path.join(folder, "cbsa.csv"), newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                self.cbsa[r["cbsa"]] = {"title": r["title"], "kind": r["kind"]}
        with open(os.path.join(folder, "counties.csv"), newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                self.county[r["fips"]] = r
        with open(os.path.join(folder, "zip_county.csv"), newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                self.zip[r["zip"]] = [r["county"]] + [x for x in r["others"].split(";") if x]
        self.principal = {}
        path = os.path.join(folder, "principal_cities.csv")
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self.principal.setdefault(r["cbsa"], []).append(r)
        path = os.path.join(folder, "ct_towns.csv")
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self.ct_town[r["town"]] = r["region"]
                    self.ct_old.setdefault(r["old_county"], set()).add(r["region"])
        meta = os.path.join(folder, "meta.json")
        self.meta = {}
        if os.path.exists(meta):
            with open(meta, encoding="utf-8") as f:
                self.meta = json.load(f)

    # ---- lookups -------------------------------------------------------------------------------
    def counties_for(self, zip_code: str, city: str = "", state: str = "") -> tuple[list[str], list[str]]:
        """Counties a listing may sit in (most likely first) and any flags about the lookup."""
        flags = []
        z = (zip_code or "")[:5]
        found = list(self.zip.get(z, []))
        if (state or "").upper() == "CT" or (found and found[0].startswith("09")):
            region = self.ct_town.get(_town(city))
            if region:
                return [region], flags
            regions = sorted({r for old in found for r in self.ct_old.get(old, set())})
            if len(regions) == 1:
                return regions, flags
            if regions:
                flags.append("Connecticut town not matched: planning region estimated from the ZIP's old county")
                return regions, flags
        if not found:
            flags.append("ZIP not in the Census ZIP file: metro area not looked up")
        elif len(found) > 1:
            names = [self.county_name(c) for c in found[1:3]]
            flags.append("ZIP also reaches " + ", ".join(n for n in names if n))
        return found, flags

    def county_name(self, fips: str) -> str:
        c = self.county.get(fips)
        return f"{c['name']}, {c['state']}" if c else ""

    def cbsa_for(self, county_fips: str) -> str:
        c = self.county.get(county_fips or "")
        return c["cbsa"] if c else ""

    def msa_label(self, cbsa_code: str) -> str:
        c = self.cbsa.get(cbsa_code or "")
        if not c:
            return ""
        return c["title"] + (" (Micro)" if c["kind"].startswith("Micro") else "")

    def counties_in(self, cbsa_code: str) -> list[dict]:
        return [c for c in self.county.values() if c["cbsa"] == cbsa_code]

    def find_cbsa(self, query: str) -> list[tuple[str, str, str]]:
        q = (query or "").strip().lower()
        if q.isdigit() and q in self.cbsa:
            return [(q, self.cbsa[q]["title"], self.cbsa[q]["kind"])]
        hits = [(code, c["title"], c["kind"]) for code, c in self.cbsa.items() if q and q in c["title"].lower()]
        return sorted(hits, key=lambda h: (not h[2].startswith("Metro"), h[1]))

    def find_county(self, text: str) -> dict | None:
        """'Durham County, NC' -> the county row."""
        m = re.match(r"\s*(.+?)\s*,\s*([A-Za-z]{2})\s*$", text or "")
        if not m:
            return None
        name, st = m.group(1).lower(), m.group(2).upper()
        for c in self.county.values():
            if c["state"] == st and c["name"].lower() in (name, name + " county"):
                return c
        return None


    def principal_cities(self, cbsa_code: str) -> list[dict]:
        """OMB's principal cities, the ones named in the metro's title first."""
        title = (self.cbsa.get(cbsa_code) or {}).get("title", "").lower()
        cities = self.principal.get(cbsa_code, [])
        return sorted(cities, key=lambda c: (title.find(c["city"].lower()) < 0, title.find(c["city"].lower()), c["city"]))


def crexi_county_url(county: dict, type_path: str = "Retail") -> str:
    """Crexi's county page for one property type, e.g. https://www.crexi.com/properties/NC/Durham_County/Retail."""
    name = re.sub(r"\s+", "_", county["name"].strip())
    return f"https://www.crexi.com/properties/{county['state']}/{name}/{type_path}"


def crexi_city_url(state: str, city: str, type_path: str = "Retail") -> str:
    """Crexi's city page, e.g. https://www.crexi.com/properties/NC/Durham/Retail."""
    return f"https://www.crexi.com/properties/{state}/{re.sub(r'[ ]+', '_', city.strip())}/{type_path}"
