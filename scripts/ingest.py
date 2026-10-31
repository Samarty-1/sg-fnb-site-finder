"""Download every input into data/raw/.  python scripts/ingest.py

- ACRA register (27 CSVs, ~660 MB): streamed, and only food & beverage rows (SSIC 56xxx)
  are kept, in data/raw/fnb_entities.parquet. Nothing else from ACRA is stored.
- Planning area boundaries (URA Master Plan 2019), MRT station exits, hawker centres.
- Residents and household income by planning area (SingStat, latest survey).
- NEA licensed eating establishments (a 2016 list, used only to check that registered
  addresses track where outlets really are).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DATA_GOV = "https://api-production.data.gov.sg/v2/public/api"
DATA_GOV_DL = "https://api-open.data.gov.sg/v1/public/api"
SINGSTAT = "https://tablebuilder.singstat.gov.sg/api/table/tabledata"

GEOJSON = {
    "planning_areas.geojson": "d_4765db0e87b9c86336792efe8a1f7a66",  # Master Plan 2019, no sea
    "mrt_exits.geojson": "d_b39d3a0871985372d7e1637193335da5",
    "hawker_centres.geojson": "d_4a086da0a5553be1d89383cd90d07ecd",
}
NEA_EATING_ESTABLISHMENTS = "d_227473e811b09731e64725f140b77697"
SINGSTAT_TABLES = {
    "residents_by_area.json": "C020125",          # resident population by planning area and dwelling
    "household_income_by_area.json": "C020146",   # households by planning area and monthly market income
}
ACRA_KEEP = ["uen", "entity_name", "entity_type_description", "entity_status_description",
             "registration_incorporation_date", "postal_code", "primary_ssic_code",
             "primary_ssic_description"]

log = logging.getLogger("ingest")
session = requests.Session()
session.headers["User-Agent"] = "sg-fnb-site-finder (+https://github.com/Samarty-1/sg-fnb-site-finder)"


def get(url: str, **kw) -> requests.Response:
    kw.setdefault("timeout", 120)
    for attempt in range(7):
        try:
            r = session.get(url, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code}", response=r)
            r.raise_for_status()
            time.sleep(0.3)
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            client_error = status is not None and 400 <= status < 500 and status != 429
            if client_error or attempt == 6:
                raise
            wait = min(60, 2 ** attempt * 2)
            log.warning("retry in %ss: %s (%s)", wait, url, e)
            time.sleep(wait)
    raise AssertionError("unreachable")


def download_url(dataset_id: str) -> str:
    data = get(f"{DATA_GOV_DL}/datasets/{dataset_id}/initiate-download").json().get("data", {})
    for _ in range(40):
        if data.get("url"):
            return data["url"]
        time.sleep(3)
        data = get(f"{DATA_GOV_DL}/datasets/{dataset_id}/poll-download").json().get("data", {})
    raise TimeoutError(dataset_id)


def fetch_dataset(dataset_id: str) -> bytes:
    return get(download_url(dataset_id), timeout=300).content


def ingest_acra() -> None:
    ids = get(f"{DATA_GOV}/collections/2/metadata").json()["data"]["collectionMetadata"]["childDatasets"]
    frames, published = [], set()
    for i, dataset_id in enumerate(ids, 1):
        published.add(get(f"{DATA_GOV}/datasets/{dataset_id}/metadata").json()["data"]["lastUpdatedAt"][:10])
        text = fetch_dataset(dataset_id).decode("utf-8-sig")
        rows = [
            {k: r.get(k, "") for k in ACRA_KEEP}
            for r in csv.DictReader(io.StringIO(text))
            if r.get("primary_ssic_code", "").startswith("56") and len(r.get("primary_ssic_code", "")) == 5
        ]
        frames.append(pd.DataFrame(rows, columns=ACRA_KEEP))
        log.info("ACRA file %d/%d: %d F&B rows", i, len(ids), len(rows))
    if len(published) != 1:
        sys.exit(f"ACRA files carry different publish dates {sorted(published)}: mid-release, try later")
    df = pd.concat(frames, ignore_index=True)
    if df["uen"].duplicated().any():
        sys.exit("duplicate UENs across ACRA files")
    df["release_date"] = published.pop()
    df.to_parquet(RAW / "fnb_entities.parquet", index=False)
    log.info("ACRA: %d F&B entities, release %s", len(df), df["release_date"].iloc[0])


def ingest_geojson() -> None:
    for name, dataset_id in GEOJSON.items():
        body = fetch_dataset(dataset_id)
        json.loads(body)  # fail loudly if it is not GeoJSON
        (RAW / name).write_bytes(body)
        log.info("%s: %d bytes", name, len(body))


def ingest_nea() -> None:
    (RAW / "nea_eating_establishments_2016.csv").write_bytes(fetch_dataset(NEA_EATING_ESTABLISHMENTS))
    log.info("NEA eating establishments landed")


def ingest_singstat() -> None:
    """Survey tables: one row per planning area (and subzone), nested columns. Small
    enough for one request; the row count is checked so a silent cap cannot truncate."""
    limit = 5000
    for name, table_id in SINGSTAT_TABLES.items():
        d = get(f"{SINGSTAT}/{table_id}", params={"limit": limit}).json()["Data"]
        if len(d["row"]) >= limit:
            sys.exit(f"{table_id}: {len(d['row'])} rows hit the request limit; add paging")
        (RAW / name).write_text(json.dumps(d, indent=1), encoding="utf-8")
        log.info("%s: %s, %s (%d rows)", name, d["title"], d.get("tableType"), len(d["row"]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    RAW.mkdir(parents=True, exist_ok=True)
    steps = sys.argv[1:] or ["singstat", "geojson", "nea", "acra"]
    for step in steps:
        globals()[f"ingest_{step}"]()
