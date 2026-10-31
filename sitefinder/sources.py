"""Read the raw inputs into tidy tables."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
REFERENCE = ROOT / "data" / "reference"


def area_key(name: str) -> str:
    """'Ang Mo Kio - Total' / 'ANG MO KIO' -> 'ANG MO KIO'."""
    return re.sub(r"\s+-\s+Total$", "", name.strip()).upper()


def _num(value) -> float:
    """SingStat writes nil as '-' and rounds to the nearest 10."""
    if value in (None, "", "-", "na"):
        return 0.0
    return float(str(value).replace(",", ""))


def residents(path: Path | None = None) -> pd.DataFrame:
    """Resident population per planning area (General Household Survey 2025)."""
    d = json.loads((path or RAW / "residents_by_area.json").read_text(encoding="utf-8"))
    rows = []
    for r in d["row"]:
        if not r["rowText"].endswith(" - Total"):
            continue
        cols = {c["key"]: c for c in r["columns"]}
        hdb = cols.get("HDB Dwellings", {})
        hdb_total = next((c["value"] for c in hdb.get("columns", []) if c["key"] == "Total"), hdb.get("value"))
        rows.append({
            "area": area_key(r["rowText"]),
            "residents": _num(cols["Total"]["value"]),
            "hdb_residents": _num(hdb_total),
        })
    df = pd.DataFrame(rows)
    df["hdb_share"] = np.where(df["residents"] > 0, df["hdb_residents"] / df["residents"].where(df["residents"] > 0), np.nan)
    return df[["area", "residents", "hdb_share"]]


def _bracket_bounds(label: str) -> tuple[float, float]:
    nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]+", label)]
    if label.startswith("Below"):
        return 0.0, nums[0]
    if "& Over" in label:
        return nums[0], np.inf
    return nums[0], nums[1] + 1


def median_from_brackets(brackets: list[tuple[float, float, float]]) -> float:
    """Median by linear interpolation inside the bracket that holds the 50th percentile.
    `brackets` is [(low, high, count)] in ascending order."""
    total = sum(c for _, _, c in brackets)
    if total <= 0:
        return float("nan")
    half, running = total / 2, 0.0
    for low, high, count in brackets:
        if count and running + count >= half:
            if np.isinf(high):
                return low  # median falls in the open top bracket: report its floor
            return low + (half - running) / count * (high - low)
        running += count
    return float("nan")


def household_income(path: Path | None = None) -> pd.DataFrame:
    """Median monthly household market income and share earning $10k+, per area (GHS 2025).
    Covers the 29 planning areas the survey reports individually."""
    d = json.loads((path or RAW / "household_income_by_area.json").read_text(encoding="utf-8"))
    rows = []
    for r in d["row"]:
        if r["rowText"] in ("Total", "Others"):
            continue
        brackets = []
        for c in r["columns"]:
            if c["key"] == "Total":
                continue
            low, high = _bracket_bounds(c["key"])
            brackets.append((low, high, _num(c["value"])))
        brackets.sort()
        total = sum(b[2] for b in brackets)
        rich = sum(cnt for low, _, cnt in brackets if low >= 10_000)
        rows.append({
            "area": area_key(r["rowText"]),
            "households": total,
            "median_household_income": round(median_from_brackets(brackets)),
            "share_households_10k_plus": rich / total if total else np.nan,
        })
    return pd.DataFrame(rows)


def fnb_entities(path: Path | None = None) -> pd.DataFrame:
    df = pd.read_parquet(path or RAW / "fnb_entities.parquet")
    df["postal_code"] = df["postal_code"].astype(str).str.strip()
    df["registration_date"] = pd.to_datetime(df["registration_incorporation_date"], errors="coerce")
    status = df["entity_status_description"].str.strip()
    df["is_live"] = status.isin(["Live", "Live Company"])
    # Converted or merged businesses carried on as another entity: neither alive nor failed.
    df["is_converted"] = status.str.startswith("Converted") | status.eq("Amalgamated") | status.eq(
        "Ceased Registration (Transferred to Singapore)")
    df["entity_kind"] = np.select(
        [df["entity_type_description"].eq("Local Company"),
         df["entity_type_description"].eq("Sole Proprietorship/ Partnership")],
        ["Company", "Sole proprietor or partnership"], "Other")
    return df


def nea_postcodes(path: Path | None = None) -> pd.Series:
    nea = pd.read_csv(path or RAW / "nea_eating_establishments_2016.csv", dtype=str)
    return nea["premises_address"].str.extract(r"SINGAPORE\s+(\d{6})\s*$")[0].dropna()


def postcode_locations(path: Path | None = None) -> pd.DataFrame:
    df = pd.read_csv(path or REFERENCE / "postcode_locations.csv", dtype={"postal_code": str})
    df = df[df["found"] == 1].copy()
    return df[["postal_code", "lat", "lng"]]


def geojson_points(name: str) -> pd.DataFrame:
    g = json.loads((RAW / name).read_text(encoding="utf-8"))
    out = []
    for f in g["features"]:
        lng, lat = f["geometry"]["coordinates"][:2]
        p = f["properties"]
        out.append({"lat": lat, "lng": lng,
                    "name": p.get("STATION_NA") or p.get("NAME") or p.get("ADDRESSBUILDINGNAME")})
    return pd.DataFrame(out)
