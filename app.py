"""Where to open a new F&B business in Singapore.

    streamlit run app.py

Reads results/area_metrics.csv (built by run.py). Move the sliders to weight what
matters to your business; the ranking and map update.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from sitefinder.score import DEFAULT_WEIGHTS, FACTORS, rank_areas

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

st.set_page_config(page_title="SG F&B site finder", layout="wide")


@st.cache_data
def load():
    metrics = pd.read_csv(RESULTS / "area_metrics.csv")
    summary = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    return metrics, summary


metrics, summary = load()

st.title("Where to open a new F&B business in Singapore")
st.caption(
    f"{summary['areas_ranked']} residential planning areas, scored on four factors from public data "
    f"(ACRA register {summary['acra_release']}, SingStat household survey 2025, LTA, NEA). "
    "A starting point for a shortlist, not a substitute for walking the street."
)

labels = {
    "residents_per_fnb": "Less competition (residents per F&B business)",
    "median_household_income": "Spending power (median household income)",
    "survival_shrunk_rate": "New F&B survive here (share still open after 4-7 years)",
    "mrt_stations": "Passing trade (MRT stations)",
}
st.sidebar.header("What matters to you?")
weights = {f: st.sidebar.slider(labels[f], 0, 10, int(round(DEFAULT_WEIGHTS[f] * 20))) for f in FACTORS}
if sum(weights.values()) == 0:
    st.warning("Give at least one factor some weight.")
    st.stop()

ranked = rank_areas(metrics, {k: float(v) for k, v in weights.items()})
show = ranked[["rank", "area", "score", "residents", "live_fnb", "residents_per_fnb",
               "median_household_income", "survival_shrunk_rate", "mrt_stations", "hawker_centres"]].copy()
show["area"] = show["area"].str.title()
show = show.rename(columns={
    "residents": "residents", "live_fnb": "live F&B businesses", "residents_per_fnb": "residents per F&B",
    "median_household_income": "median household income ($/month)",
    "survival_shrunk_rate": "new F&B still open", "mrt_stations": "MRT stations", "hawker_centres": "hawker centres",
})

left, right = st.columns([3, 2])
with left:
    st.subheader("Ranking")
    st.dataframe(
        show.style.format({"score": "{:.2f}", "residents": "{:,.0f}", "residents per F&B": "{:,.0f}",
                           "median household income ($/month)": "${:,.0f}", "new F&B still open": "{:.0%}"}),
        hide_index=True, width="stretch", height=560)
with right:
    st.subheader("Competition vs spending power")
    fig = px.scatter(ranked.assign(area=ranked["area"].str.title()), x="residents_per_fnb",
                     y="median_household_income", size="residents", color="score",
                     color_continuous_scale="Blues", hover_name="area",
                     labels={"residents_per_fnb": "Residents per F&B business (higher = less crowded)",
                             "median_household_income": "Median household income ($/month)",
                             "score": "Score"})
    fig.update_layout(height=560, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    st.plotly_chart(fig, width="stretch")

st.markdown(
    "**How to read it.** Each factor is turned into a percentile among these areas (0 = worst, 1 = best) "
    "and the score is the weighted average. Survival uses statistical shrinkage: an area with few new "
    "F&B businesses is pulled toward the island-wide rate instead of looking perfect or hopeless by chance. "
    "Business counts use ACRA *registered* addresses; the README shows how well they track real outlets."
)
