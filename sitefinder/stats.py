"""Small-sample statistics for area comparisons."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def beta_binomial_prior(successes: np.ndarray, trials: np.ndarray) -> tuple[float, float]:
    """Fit a Beta(alpha, beta) prior to area survival rates by the method of moments.

    The spread of observed rates is partly real differences between areas and partly
    noise from small samples. Subtracting the expected noise leaves the between-area
    variance, which sets how strongly each area is pulled toward the overall rate.

    The spread is weighted by cohort size, so the noise subtracted must be weighted
    the same way. For weights w = n / N around the pooled rate mu,

        E[sum w (p - mu)^2] = tau^2 (1 - sum w^2) + mu (1 - mu) (K - 1) / N

    where tau^2 is the between-area variance and K the number of areas. Using the
    unweighted mean of 1/n instead (as this function once did) overstates the noise
    whenever cohort sizes differ: on the real areas (8 to 749 companies) it put the
    prior strength at 925 instead of 130, pulling every area most of the way to the
    island-wide rate. tests/test_sitefinder.py checks the estimate against simulated
    areas with a known spread."""
    successes, trials = np.asarray(successes, float), np.asarray(trials, float)
    keep = trials > 0
    s, n = successes[keep], trials[keep]
    if len(n) < 3:
        raise ValueError("need at least 3 areas with data to estimate how much areas differ")
    p = s / n
    total = n.sum()
    mean = s.sum() / total
    weights = n / total
    observed_var = np.sum(weights * (p - mean) ** 2)
    noise_var = mean * (1 - mean) * (len(n) - 1) / total
    between = max((observed_var - noise_var) / (1 - np.sum(weights ** 2)), 1e-6)
    strength = max(mean * (1 - mean) / between - 1, 1.0)  # alpha + beta
    return mean * strength, (1 - mean) * strength


def shrunk_rates(successes, trials, level: float = 0.9) -> pd.DataFrame:
    """Posterior mean and credible interval for each area's rate under the fitted prior."""
    successes, trials = np.asarray(successes, float), np.asarray(trials, float)
    a, b = beta_binomial_prior(successes, trials)
    post_a, post_b = a + successes, b + trials - successes
    lo, hi = stats.beta.ppf([(1 - level) / 2, (1 + level) / 2], post_a[:, None], post_b[:, None]).T
    return pd.DataFrame({
        "raw_rate": np.where(trials > 0, successes / np.where(trials > 0, trials, 1), np.nan),
        "shrunk_rate": post_a / (post_a + post_b),
        "ci_low": lo,
        "ci_high": hi,
        "prior_strength": a + b,
    })


def spearman(x, y) -> float:
    return float(stats.spearmanr(x, y).statistic)
