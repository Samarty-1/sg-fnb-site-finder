"""Draw the README charts from results/.  python scripts/charts.py"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402
from matplotlib.patches import Polygon as MplPolygon  # noqa: E402
from shapely.geometry import shape  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS, DOCS, RAW = ROOT / "results", ROOT / "docs", ROOT / "data" / "raw"
INK, MUTED, GRID, SURFACE, NODATA = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#e9e8e4"
BLUES = LinearSegmentedColormap.from_list("blues", ["#cde2fb", "#86b6ef", "#2a78d6", "#184f95", "#0d366b"])
FACTOR_COLOURS = {"residents_per_fnb": "#2a78d6", "median_household_income": "#eb6834",
                  "survival_shrunk_rate": "#1baf7a", "mrt_stations": "#eda100"}
FACTOR_LABELS = {"residents_per_fnb": "Less competition", "median_household_income": "Spending power",
                 "survival_shrunk_rate": "New F&B survive", "mrt_stations": "MRT access"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
})


def score_map(ranking: pd.DataFrame) -> None:
    g = json.loads((RAW / "planning_areas.geojson").read_text(encoding="utf-8"))
    score = ranking.set_index("area")["score"]
    lo, hi = score.min(), score.max()
    fig, ax = plt.subplots(figsize=(9, 5.4))
    for f in g["features"]:
        name = f["properties"]["PLN_AREA_N"].upper()
        geom = shape(f["geometry"])
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        colour = BLUES((score[name] - lo) / (hi - lo)) if name in score.index else NODATA
        for poly in polys:
            ax.add_patch(MplPolygon(list(poly.exterior.coords), closed=True, facecolor=colour,
                                    edgecolor=SURFACE, linewidth=0.8))
    for _, r in ranking.head(5).iterrows():
        f = next(x for x in g["features"] if x["properties"]["PLN_AREA_N"].upper() == r["area"])
        c = shape(f["geometry"]).representative_point()
        # Labels spill past small polygons onto grey and pale fills, so use dark text
        # with a white halo, which reads on every background.
        ax.annotate(f"{int(r['rank'])}. {r['area'].title()}", (c.x, c.y), ha="center", va="center",
                    fontsize=8.5, color=INK, fontweight="bold",
                    path_effects=[patheffects.withStroke(linewidth=2.5, foreground="white")])
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.axis("off")
    sm = plt.cm.ScalarMappable(cmap=BLUES, norm=Normalize(float(lo), float(hi)))
    cb = fig.colorbar(sm, ax=ax, shrink=0.55, pad=0.01)
    cb.set_label("Score (higher = better for a new F&B)", color=MUTED)
    cb.outline.set_visible(False)
    ax.set_title("Where a new F&B business has the best odds, by planning area", loc="left",
                 fontsize=12, color=INK)
    fig.text(0.01, 0.02, "Grey: industrial, CBD or nature areas the household survey does not cover. "
             "Default weights; the dashboard lets you change them.", fontsize=8, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(DOCS / "score_map.png", dpi=150)
    plt.close(fig)


def top_breakdown(ranking: pd.DataFrame, weights: dict) -> None:
    top = ranking.head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    left = pd.Series(0.0, index=top.index)
    for f, colour in FACTOR_COLOURS.items():
        part = top[f"pct_{f}"] * weights[f]
        ax.barh(top["area"].str.title(), part, left=left, color=colour, height=0.66,
                edgecolor=SURFACE, linewidth=2, label=FACTOR_LABELS[f])
        left += part
    for y, s in enumerate(top["score"]):
        ax.text(s + 0.01, y, f"{s:.2f}", va="center", fontsize=8.5, color=INK)
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("Score: weighted average of each factor's percentile")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(ncol=4, loc="lower center", bbox_to_anchor=(0.45, 1.0), frameon=False, fontsize=9)
    ax.set_title("Top 10 areas, and what puts them there", loc="left", fontsize=12, color=INK, pad=28)
    fig.tight_layout()
    fig.savefig(DOCS / "top10_breakdown.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    DOCS.mkdir(exist_ok=True)
    ranking = pd.read_csv(RESULTS / "ranking.csv")
    summary = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    score_map(ranking)
    top_breakdown(ranking, summary["default_weights"])
