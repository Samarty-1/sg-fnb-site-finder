"""Build one row per planning area with everything the ranking needs."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import sources
from .geo import PlanningAreas
from .stats import shrunk_rates, spearman

# A new business is judged on whether it is still live after roughly 4 to 7 years:
# registered 2019-2022, observed at the latest ACRA release.
SURVIVAL_COHORT = (2019, 2022)


@dataclass
class Coverage:
    entities: int
    with_valid_postcode: int
    located: int
    # Only live businesses and those registered from 2019 on feed any metric, so only
    # their postcodes are geocoded (scripts/geocode.py). Coverage that matters is of these.
    in_scope: int
    in_scope_located: int


def locate_entities(fnb: pd.DataFrame, locations: pd.DataFrame, areas: PlanningAreas) -> tuple[pd.DataFrame, Coverage]:
    valid = fnb["postal_code"].str.fullmatch(r"\d{6}") & fnb["postal_code"].str[:2].between("01", "82")
    df = fnb.merge(locations, on="postal_code", how="left")
    df["area"] = None
    has = df["lat"].notna()
    df.loc[has, "area"] = areas.locate_frame(df.loc[has])
    scope = df["is_live"] | (df["registration_date"].dt.year >= SURVIVAL_COHORT[0])
    cov = Coverage(len(fnb), int(valid.sum()), int(df["area"].notna().sum()),
                   int(scope.sum()), int((scope & df["area"].notna()).sum()))
    return df, cov


def area_metrics(fnb: pd.DataFrame, locations: pd.DataFrame, areas: PlanningAreas,
                 residents: pd.DataFrame, income: pd.DataFrame, mrt: pd.DataFrame,
                 hawkers: pd.DataFrame, nea_codes: pd.Series) -> tuple[pd.DataFrame, Coverage]:
    located, cov = locate_entities(fnb, locations, areas)
    release_year = pd.to_datetime(fnb["release_date"].iloc[0]).year
    recent = (release_year - 3, release_year - 1)  # last three full calendar years
    year = located["registration_date"].dt.year

    live = located[located["is_live"]].groupby("area").size().rename("live_fnb")
    new = located[year.between(*recent)].groupby("area").size().rename("new_fnb_last_3y")
    cohort = located[year.between(*SURVIVAL_COHORT) & ~located["is_converted"]
                     & located["entity_kind"].eq("Company")]
    surv = cohort.groupby("area").agg(cohort_registered=("uen", "size"), cohort_still_live=("is_live", "sum"))

    mrt = mrt.assign(area=areas.locate_frame(mrt))
    stations = mrt.groupby("area")["name"].nunique().rename("mrt_stations")
    hawkers = hawkers.assign(area=areas.locate_frame(hawkers))
    hawker_n = hawkers.groupby("area").size().rename("hawker_centres")

    nea = pd.DataFrame({"postal_code": nea_codes}).merge(locations, on="postal_code", how="inner")
    nea["area"] = areas.locate_frame(nea)
    nea_n = nea.groupby("area").size().rename("nea_outlets_2016")

    out = (pd.DataFrame({"area": areas.names, "region": [areas.region_of()[a] for a in areas.names]})
           .merge(residents, on="area", how="left")
           .merge(income, on="area", how="left")
           .set_index("area")
           .join([live, new, surv, stations, hawker_n, nea_n])
           .reset_index())
    counts = ["live_fnb", "new_fnb_last_3y", "cohort_registered", "cohort_still_live", "mrt_stations",
              "hawker_centres", "nea_outlets_2016"]
    out[counts] = out[counts].fillna(0).astype(int)
    out["residents"] = out["residents"].fillna(0)
    out["residents_per_fnb"] = (out["residents"] / out["live_fnb"].where(out["live_fnb"] > 0)).round(1)
    out["fnb_per_10k_residents"] = (out["live_fnb"] / out["residents"].where(out["residents"] > 0) * 1e4).round(1)

    # Survival is only compared across the residential areas the ranking covers.
    scope = out["median_household_income"].notna()
    rates = shrunk_rates(out.loc[scope, "cohort_still_live"], out.loc[scope, "cohort_registered"])
    for col in ["raw_rate", "shrunk_rate", "ci_low", "ci_high"]:
        out.loc[scope, f"survival_{col}"] = rates[col].to_numpy()
    out = out.sort_values("area").reset_index(drop=True)
    out.attrs["release_date"] = str(fnb["release_date"].iloc[0])
    out.attrs["recent_years"] = recent
    out.attrs["prior_strength"] = float(rates["prior_strength"].iloc[0]) if len(rates) else float("nan")
    return out, cov


def registered_address_check(metrics: pd.DataFrame) -> dict:
    """Do ACRA registered addresses track where outlets really trade? Compare live F&B
    businesses per area with NEA's 2016 list of licensed eating establishments."""
    m = metrics[(metrics["nea_outlets_2016"] > 0) | (metrics["live_fnb"] > 0)].copy()
    rho_all = spearman(m["live_fnb"], m["nea_outlets_2016"])
    res = metrics[metrics["median_household_income"].notna()]
    rho_res = spearman(res["live_fnb"], res["nea_outlets_2016"])
    m["acra_to_nea"] = m["live_fnb"] / m["nea_outlets_2016"].where(m["nea_outlets_2016"] > 0)
    overall = m["live_fnb"].sum() / m["nea_outlets_2016"].sum()
    m["over_representation"] = m["acra_to_nea"] / overall
    return {"spearman_all_areas": rho_all, "spearman_residential": rho_res,
            "table": m[["area", "live_fnb", "nea_outlets_2016", "over_representation"]]
            .sort_values("over_representation", ascending=False)}


def load_and_build() -> tuple[pd.DataFrame, Coverage]:
    areas = PlanningAreas()
    return area_metrics(
        sources.fnb_entities(), sources.postcode_locations(), areas,
        sources.residents(), sources.household_income(),
        sources.geojson_points("mrt_exits.geojson"), sources.geojson_points("hawker_centres.geojson"),
        sources.nea_postcodes(),
    )
