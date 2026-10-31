"""Unit and end-to-end tests on small hand-made inputs (no network, no real data)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from sitefinder import sources
from sitefinder.build import area_metrics, registered_address_check
from sitefinder.geo import PlanningAreas
from sitefinder.score import DEFAULT_WEIGHTS, FACTORS, rank_areas, weight_sensitivity
from sitefinder.stats import shrunk_rates


# ------------------------------------------------------------------ parsing

def test_area_key():
    assert sources.area_key("Ang Mo Kio - Total") == "ANG MO KIO"
    assert sources.area_key(" Bedok ") == "BEDOK"


def test_median_from_brackets_interpolates():
    # 10 below 1000, 10 in 1000-2000: median is the top of the first bracket
    assert sources.median_from_brackets([(0, 1000, 10), (1000, 2000, 10)]) == pytest.approx(1000)
    # 40 households: the 20th sits a quarter of the way into the 2000-3000 bracket
    assert sources.median_from_brackets([(0, 1000, 10), (1000, 2000, 5), (2000, 3000, 20), (3000, 4000, 5)]) \
        == pytest.approx(2250)
    assert sources.median_from_brackets([(0, 1000, 1), (5000, np.inf, 5)]) == 5000
    assert np.isnan(sources.median_from_brackets([(0, 1000, 0)]))


def test_bracket_bounds():
    assert sources._bracket_bounds("Below $1,000") == (0, 1000)
    assert sources._bracket_bounds("$1,000 - $1,999") == (1000, 2000)
    assert sources._bracket_bounds("$25,000 -$29,999") == (25000, 30000)
    assert sources._bracket_bounds("$35,000 & Over") == (35000, np.inf)


def test_survey_tables_parse(tmp_path):
    res = {"row": [
        {"rowText": "Total", "columns": [{"key": "Total", "value": "999"}]},
        {"rowText": "Bedok - Total", "columns": [
            {"key": "Total", "value": "1000"},
            {"key": "HDB Dwellings", "columns": [{"key": "Total", "value": "750"}]}]},
        {"rowText": "Bedok North", "columns": [{"key": "Total", "value": "400"}]},
        {"rowText": "Changi Bay - Total", "columns": [{"key": "Total", "value": "-"},
                                                      {"key": "HDB Dwellings", "value": "-"}]},
    ]}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(res))
    df = sources.residents(p).set_index("area")
    assert list(df.index) == ["BEDOK", "CHANGI BAY"]
    assert df.loc["BEDOK", "residents"] == 1000 and df.loc["BEDOK", "hdb_share"] == 0.75
    assert df.loc["CHANGI BAY", "residents"] == 0 and np.isnan(df.loc["CHANGI BAY", "hdb_share"])

    inc = {"row": [
        {"rowText": "Bedok", "columns": [
            {"key": "Total", "value": "40"}, {"key": "Below $1,000", "value": "10"},
            {"key": "$10,000 - $10,999", "value": "20"}, {"key": "$35,000 & Over", "value": "10"}]},
        {"rowText": "Others", "columns": [{"key": "Total", "value": "5"}]},
    ]}
    p2 = tmp_path / "i.json"
    p2.write_text(json.dumps(inc))
    df2 = sources.household_income(p2).set_index("area")
    assert list(df2.index) == ["BEDOK"]
    assert df2.loc["BEDOK", "share_households_10k_plus"] == 0.75
    assert df2.loc["BEDOK", "median_household_income"] == 10500


# ------------------------------------------------------------------ geography

@pytest.fixture
def areas(tmp_path):
    """Three unit squares side by side: WEST [0,1], EAST [1,2] and FAR [2,3] (y in [0,1])."""
    def square(x0):
        return [[[x0, 0], [x0 + 1, 0], [x0 + 1, 1], [x0, 1], [x0, 0]]]
    g = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"PLN_AREA_N": "WEST", "REGION_N": "W"},
         "geometry": {"type": "Polygon", "coordinates": square(0)}},
        {"type": "Feature", "properties": {"PLN_AREA_N": "EAST", "REGION_N": "E"},
         "geometry": {"type": "Polygon", "coordinates": square(1)}},
        {"type": "Feature", "properties": {"PLN_AREA_N": "FAR", "REGION_N": "E"},
         "geometry": {"type": "Polygon", "coordinates": square(2)}},
    ]}
    p = tmp_path / "areas.geojson"
    p.write_text(json.dumps(g))
    return PlanningAreas(p)


def test_points_land_in_the_right_area(areas):
    got = areas.locate(np.array([0.5, 1.5, 2.5, 5.0]), np.array([0.5, 0.5, 0.5, 5.0]))
    assert list(got) == ["WEST", "EAST", "FAR", None]


def test_a_boundary_point_is_assigned_once(areas):
    got = areas.locate(np.array([1.0]), np.array([0.5]))
    assert got[0] in {"WEST", "EAST"}


# ------------------------------------------------------------------ statistics

def test_shrinkage_pulls_small_areas_harder():
    # same raw rate (20%) in a tiny and a large area; overall rate is much higher
    successes = np.array([1, 200, 300, 280, 320])
    trials = np.array([5, 1000, 500, 500, 500])
    r = shrunk_rates(successes, trials)
    pooled = successes.sum() / trials.sum()
    assert r.loc[0, "raw_rate"] == r.loc[1, "raw_rate"] == 0.2
    assert r.loc[1, "shrunk_rate"] == pytest.approx(0.2, abs=0.01)   # big area barely moves
    assert 0.2 < r.loc[0, "shrunk_rate"] < pooled                    # tiny area pulled toward pooled
    assert (r["ci_low"] <= r["shrunk_rate"]).all() and (r["shrunk_rate"] <= r["ci_high"]).all()
    assert r.loc[0, "ci_high"] - r.loc[0, "ci_low"] > r.loc[1, "ci_high"] - r.loc[1, "ci_low"]


def test_area_with_no_cohort_gets_the_prior():
    r = shrunk_rates(np.array([0, 50, 60, 55]), np.array([0, 100, 100, 100]))
    assert np.isnan(r.loc[0, "raw_rate"])
    assert 0.5 <= r.loc[0, "shrunk_rate"] <= 0.6


def test_too_few_areas_is_an_error_not_a_guess():
    with pytest.raises(ValueError):
        shrunk_rates(np.array([5, 6]), np.array([10, 10]))


# ------------------------------------------------------------------ scoring

def metrics_frame(n=6):
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "area": [f"A{i}" for i in range(n)],
        "residents_per_fnb": rng.uniform(50, 300, n),
        "median_household_income": rng.uniform(5000, 15000, n),
        "survival_shrunk_rate": rng.uniform(0.4, 0.7, n),
        "mrt_stations": rng.integers(0, 6, n),
        "live_fnb": 10,
    })
    # A0 is best on every factor
    df.loc[0, list(FACTORS)] = [1000, 30000, 0.95, 10]
    return df


def test_dominant_area_ranks_first_under_any_weights():
    df = metrics_frame()
    assert rank_areas(df).iloc[0]["area"] == "A0"
    for f in FACTORS:
        w = {k: (1.0 if k == f else 0.0) for k in FACTORS}
        assert rank_areas(df, w).iloc[0]["area"] == "A0"
    s = weight_sensitivity(df, draws=500, top=1)
    assert s.iloc[0]["area"] == "A0" and s.iloc[0]["share_of_weightings_in_top"] == 1.0


def test_areas_without_income_data_are_out_of_scope():
    df = metrics_frame()
    df.loc[5, "median_household_income"] = np.nan
    assert "A5" not in set(rank_areas(df)["area"])


def test_bad_weights_are_rejected():
    df = metrics_frame()
    with pytest.raises(ValueError):
        rank_areas(df, {"residents_per_fnb": 1.0})
    with pytest.raises(ValueError):
        rank_areas(df, {k: -1.0 for k in FACTORS})


def test_sensitivity_is_reproducible():
    df = metrics_frame()
    pd.testing.assert_frame_equal(weight_sensitivity(df, draws=300), weight_sensitivity(df, draws=300))


def test_default_weights_sum_to_one():
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


# ------------------------------------------------------------------ end to end

def test_area_metrics_end_to_end(areas):
    fnb = pd.DataFrame({
        "uen": ["1", "2", "3", "4", "5", "6", "7", "8", "9"],
        "postal_code": ["100001", "100001", "200002", "200002", "999999", "0718", "300003", "300003", "200002"],
        "registration_date": pd.to_datetime(["2020-05-01", "2021-01-01", "2024-03-01", "2019-06-01",
                                             "2024-01-01", "2020-01-01", "2022-02-01", "2019-09-01", "2020-07-01"]),
        "is_live": [True, False, True, False, True, True, True, True, False],
        "is_converted": [False, False, False, True, False, False, False, False, False],
        "entity_kind": ["Company", "Company", "Company", "Company", "Company", "Sole proprietor or partnership",
                        "Company", "Company", "Company"],
        "release_date": "2026-10-14",
    })
    locations = pd.DataFrame({"postal_code": ["100001", "200002", "300003"],
                              "lat": [0.5, 0.5, 0.5], "lng": [0.5, 1.5, 2.5]})
    residents = pd.DataFrame({"area": ["WEST", "EAST", "FAR"], "residents": [1000.0, 3000.0, 500.0],
                              "hdb_share": [0.8, 0.5, 0.9]})
    income = pd.DataFrame({"area": ["WEST", "EAST", "FAR"], "households": [300, 900, 150],
                           "median_household_income": [8000, 12000, 6000],
                           "share_households_10k_plus": [0.3, 0.6, 0.2]})
    mrt = pd.DataFrame({"lat": [0.2, 0.3, 0.4], "lng": [1.2, 1.3, 0.4], "name": ["S1", "S1", "S2"]})
    hawkers = pd.DataFrame({"lat": [0.5], "lng": [0.5], "name": ["H"]})
    nea = pd.Series(["100001", "100001", "300003", "200002"])

    m, cov = area_metrics(fnb, locations, areas, residents, income, mrt, hawkers, nea)
    m = m.set_index("area")
    assert (cov.entities, cov.located) == (9, 7)  # 999999 not geocoded, 0718 invalid
    assert m.loc["WEST", "live_fnb"] == 1 and m.loc["EAST", "live_fnb"] == 1
    assert m.loc["EAST", "new_fnb_last_3y"] == 1          # 2024 is within 2023-2025
    # WEST cohort: two companies registered 2020-21, one still live
    assert (m.loc["WEST", "cohort_registered"], m.loc["WEST", "cohort_still_live"]) == (2, 1)
    # EAST: the 2019 company converted, so only the closed 2020 company counts
    assert (m.loc["EAST", "cohort_registered"], m.loc["EAST", "cohort_still_live"]) == (1, 0)
    assert (m.loc["WEST", "mrt_stations"], m.loc["EAST", "mrt_stations"]) == (1, 1)
    assert m.loc["WEST", "hawker_centres"] == 1
    assert (m.loc["WEST", "nea_outlets_2016"], m.loc["EAST", "nea_outlets_2016"]) == (2, 1)
    assert (m.loc["FAR", "cohort_registered"], m.loc["FAR", "cohort_still_live"]) == (2, 2)
    # shrinkage keeps every area's survival between 0 and 1 and inside its own interval
    assert m["survival_shrunk_rate"].between(0, 1).all()
    assert (m["survival_ci_low"] <= m["survival_shrunk_rate"]).all()
    assert m.loc["EAST", "residents_per_fnb"] == 3000


def test_registered_address_check_flags_office_districts():
    m = pd.DataFrame({
        "area": ["CBD", "TOWN1", "TOWN2", "TOWN3"],
        "live_fnb": [400, 100, 200, 300],
        "nea_outlets_2016": [100, 100, 200, 300],      # outlets: the CBD has far fewer than registrations
        "median_household_income": [np.nan, 1, 1, 1],
    })
    check = registered_address_check(m)
    assert check["spearman_residential"] == pytest.approx(1.0)
    top = check["table"].iloc[0]
    assert top["area"] == "CBD" and top["over_representation"] > 2
