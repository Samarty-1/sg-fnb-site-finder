"""Rank residential planning areas for a new F&B business, and test how much the
ranking depends on the weights chosen."""
from __future__ import annotations

import numpy as np
import pandas as pd

# Each factor, and which direction is good for a newcomer.
FACTORS = {
    "residents_per_fnb": "More residents per existing F&B business: less competition",
    "median_household_income": "Higher household income: more to spend on eating out",
    "survival_shrunk_rate": "New F&B companies here more often still open years later",
    "mrt_stations": "More MRT stations: more passing trade",
}
DEFAULT_WEIGHTS = {"residents_per_fnb": 0.35, "median_household_income": 0.25,
                   "survival_shrunk_rate": 0.25, "mrt_stations": 0.15}


def residential_scope(metrics: pd.DataFrame) -> pd.DataFrame:
    """The areas the household survey reports income for: the residential towns."""
    return metrics[metrics["median_household_income"].notna() & (metrics["live_fnb"] > 0)].copy()


def factor_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Each factor as a percentile (0 = worst area, 1 = best), so units don't matter."""
    return pd.DataFrame({f: df[f].rank(pct=True, method="average") for f in FACTORS}, index=df.index)


def rank_areas(metrics: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    weights = weights or DEFAULT_WEIGHTS
    if set(weights) != set(FACTORS):
        raise ValueError(f"weights must cover exactly {sorted(FACTORS)}")
    total = sum(weights.values())
    if total <= 0 or any(w < 0 for w in weights.values()):
        raise ValueError("weights must be non-negative and not all zero")
    df = residential_scope(metrics)
    scores = factor_scores(df)
    df["score"] = sum(scores[f] * w / total for f, w in weights.items())
    for f in FACTORS:
        df[f"pct_{f}"] = scores[f]
    df["rank"] = df["score"].rank(ascending=False, method="min").astype(int)
    return df.sort_values(["rank", "area"]).reset_index(drop=True)


def weight_sensitivity(metrics: pd.DataFrame, draws: int = 5000, top: int = 5, seed: int = 7) -> pd.DataFrame:
    """Re-rank under thousands of random weightings (uniform over all weight mixes).
    An area that is top-5 under most of them does not depend on one person's weights."""
    df = residential_scope(metrics)
    scores = factor_scores(df).to_numpy()
    rng = np.random.default_rng(seed)
    w = rng.dirichlet(np.ones(len(FACTORS)), size=draws)          # draws x factors
    totals = scores @ w.T                                          # areas x draws
    ranks = (-totals).argsort(axis=0).argsort(axis=0) + 1          # 1 = best
    return (pd.DataFrame({
        "area": df["area"].to_numpy(),
        "share_of_weightings_in_top": (ranks <= top).mean(axis=1),
        "median_rank": np.median(ranks, axis=1),
        "best_rank": ranks.min(axis=1),
        "worst_rank": ranks.max(axis=1),
    }).sort_values(["share_of_weightings_in_top", "median_rank"], ascending=[False, True])
      .reset_index(drop=True))
