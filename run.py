"""Build the area table, the ranking, the weight-sensitivity check and the address check.

    python scripts/ingest.py     # download inputs (~660 MB streamed, ~4 MB kept)
    python scripts/geocode.py    # only needed for postcodes not already in the cache
    python run.py                # writes results/*.csv
"""
from __future__ import annotations

import json
from pathlib import Path

from sitefinder.build import SURVIVAL_COHORT, load_and_build, registered_address_check
from sitefinder.score import DEFAULT_WEIGHTS, rank_areas, weight_sensitivity

RESULTS = Path(__file__).resolve().parent / "results"


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    metrics, coverage = load_and_build()
    metrics.to_csv(RESULTS / "area_metrics.csv", index=False)

    ranking = rank_areas(metrics)
    ranking.to_csv(RESULTS / "ranking.csv", index=False)
    sensitivity = weight_sensitivity(metrics)
    sensitivity.to_csv(RESULTS / "weight_sensitivity.csv", index=False)
    check = registered_address_check(metrics)
    check["table"].to_csv(RESULTS / "registered_address_check.csv", index=False)

    summary = {
        "acra_release": str(metrics.attrs.get("release_date", "")),
        "fnb_entities": coverage.entities,
        "with_valid_postcode": coverage.with_valid_postcode,
        "located_in_a_planning_area": coverage.located,
        "areas_ranked": len(ranking),
        "survival_cohort": list(SURVIVAL_COHORT),
        "recent_years": list(metrics.attrs["recent_years"]),
        "survival_prior_strength": round(metrics.attrs["prior_strength"], 1),
        "default_weights": DEFAULT_WEIGHTS,
        "spearman_acra_vs_nea_all_areas": round(check["spearman_all_areas"], 3),
        "spearman_acra_vs_nea_residential": round(check["spearman_residential"], 3),
    }
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    cols = ["rank", "area", "score", "residents_per_fnb", "median_household_income",
            "survival_shrunk_rate", "mrt_stations"]
    print(json.dumps(summary, indent=2))
    print(ranking[cols].head(10).to_string(index=False))
    print(sensitivity.head(8).to_string(index=False))
    print(check["table"].head(8).to_string(index=False))


if __name__ == "__main__":
    main()
