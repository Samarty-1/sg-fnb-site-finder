"""Small-sample statistics for area comparisons."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def beta_binomial_prior(successes: np.ndarray, trials: np.ndarray) -> tuple[float, float]:
    """Fit a Beta(alpha, beta) prior to area survival rates by the method of moments.

    The spread of observed rates is partly real differences between areas and partly
    noise from small samples. Subtracting the expected noise leaves the between-area
    variance, which sets how strongly each area is pulled toward the overall rate."""
    successes, trials = np.asarray(successes, float), np.asarray(trials, float)
    keep = trials > 0
    s, n = successes[keep], trials[keep]
    if len(n) < 3:
        raise ValueError("need at least 3 areas with data to estimate how much areas differ")
    p = s / n
    mean = s.sum() / n.sum()
    weights = n / n.sum()
    observed_var = np.sum(weights * (p - mean) ** 2)
    noise_var = mean * (1 - mean) * np.mean(1 / n)
    between = max(observed_var - noise_var, 1e-6)
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
