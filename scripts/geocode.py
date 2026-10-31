"""Postcode -> latitude/longitude with OneMap, cached.  python scripts/geocode.py

Every Singapore postcode is one building, so a postcode is a precise location.
Results are cached in data/reference/postcode_locations.csv, which is committed:
re-running only looks up postcodes not already in the cache, and nobody else has to
repeat the ~16,000 lookups. Without an API key OneMap accepts about one request a
second (measured: 2 a second gets half the requests refused), so a cold run takes
about 4.5 hours.
"""
from __future__ import annotations

import csv
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "reference" / "postcode_locations.csv"
FIELDS = ["postal_code", "found", "lat", "lng", "building"]
ONEMAP = "https://www.onemap.gov.sg/api/common/elastic/search"
MIN_INTERVAL = 1.05  # seconds between requests; OneMap's keyless limit is ~1/s

log = logging.getLogger("geocode")
VALID = re.compile(r"\d{6}")


def wanted_postcodes() -> set[str]:
    fnb = pd.read_parquet(RAW / "fnb_entities.parquet")
    # The analysis uses live businesses and those registered from 2019 on.
    live = fnb["entity_status_description"].str.strip().isin(["Live", "Live Company"])
    recent = fnb["registration_incorporation_date"].str[:4] >= "2019"
    fnb = fnb[live | recent]
    codes = {p for p in fnb["postal_code"].astype(str).str.strip() if VALID.fullmatch(p) and "01" <= p[:2] <= "82"}
    nea = pd.read_csv(RAW / "nea_eating_establishments_2016.csv", dtype=str)
    for addr in nea["premises_address"].dropna():
        m = re.search(r"SINGAPORE\s+(\d{6})\s*$", addr)
        if m and "01" <= m.group(1)[:2] <= "82":
            codes.add(m.group(1))
    return codes


def load_cache() -> dict[str, dict]:
    if not CACHE.exists():
        return {}
    with CACHE.open(newline="", encoding="utf-8") as f:
        return {r["postal_code"]: r for r in csv.DictReader(f)}


def save_cache(cache: dict[str, dict]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for code in sorted(cache):
            w.writerow({k: cache[code].get(k, "") for k in FIELDS})
    tmp.replace(CACHE)


def lookup(session: requests.Session, code: str) -> dict:
    for attempt in range(6):
        try:
            r = session.get(ONEMAP, params={"searchVal": code, "returnGeom": "Y", "getAddrDetails": "N",
                                            "pageNum": 1}, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(str(r.status_code))
            r.raise_for_status()
            results = r.json().get("results", [])
            break
        except (requests.RequestException, ValueError) as e:
            wait = min(120, 5 * 2 ** attempt)
            log.warning("%s: %s, retry in %ss", code, e, wait)
            time.sleep(wait)
    else:
        raise RuntimeError(f"OneMap kept failing for {code}")
    if not results:
        return {"postal_code": code, "found": "0", "lat": "", "lng": "", "building": ""}
    top = results[0]
    return {"postal_code": code, "found": "1", "lat": top["LATITUDE"], "lng": top["LONGITUDE"],
            "building": top.get("SEARCHVAL", "")}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cache = load_cache()
    todo = sorted(wanted_postcodes() - cache.keys())
    log.info("%d postcodes cached, %d to look up (~%.0f min)", len(cache), len(todo),
             len(todo) * MIN_INTERVAL / 60)
    session = requests.Session()
    session.headers["User-Agent"] = "sg-fnb-site-finder (+https://github.com/Samarty-1/sg-fnb-site-finder)"
    last = 0.0
    for i, code in enumerate(todo, 1):
        time.sleep(max(0.0, MIN_INTERVAL - (time.monotonic() - last)))
        last = time.monotonic()
        cache[code] = lookup(session, code)
        if i % 250 == 0 or i == len(todo):
            save_cache(cache)
            log.info("%d/%d done", i, len(todo))
    save_cache(cache)
    found = sum(r["found"] == "1" for r in cache.values())
    log.info("cache: %d postcodes, %d located (%.1f%%)", len(cache), found, 100 * found / max(1, len(cache)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
