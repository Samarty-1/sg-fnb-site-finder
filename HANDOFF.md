# Handoff: finishing sg-fnb-site-finder (delete this file before going public)

Status at 2026-10-31 20:50 (desktop):
- Code and 16 tests done.
- Postcode geocoding is 15,000 of 15,887 done. The cache is in `data/reference/postcode_locations.csv`, and the script resumes from it.
- `data/raw/` (git-ignored) is attached to the `handoff` release as `raw.zip`, so ACRA does not need to be downloaded again.
- This repo is PRIVATE until finished.

## On the new machine

```bash
gh repo clone Samarty-1/sg-fnb-site-finder && cd sg-fnb-site-finder
gh release download handoff -p raw.zip && unzip raw.zip -d data/   # restores data/raw/
python -m venv .venv && source .venv/Scripts/activate              # Windows Git Bash
pip install -r requirements.txt
PYTHONIOENCODING=utf-8 python scripts/geocode.py                   # ~15 min, finishes the last ~887
```

Then, in Claude Code, say: "read HANDOFF.md and finish the repo".

## Remaining steps for Claude

1. Check that geocoding is complete (about 98% of postcodes should be found).
2. `python run.py`, then review results/: coverage, Spearman ACRA vs NEA, ranking, weight sensitivity.
3. `python scripts/charts.py`, then look at docs/score_map.png and docs/top10_breakdown.png.
4. Add a Streamlit AppTest test for app.py (like sg-retail-demand-forecast/tests/test_app.py).
5. Write a plain-English README using only verified numbers, in the same style as the sibling repos sg-business-pulse and sg-retail-demand-forecast.
6. Run pytest in a clean venv.
7. Delete this file, delete the `handoff` release (`gh release delete handoff --cleanup-tag`), commit, push, then `gh repo edit --visibility public --accept-visibility-change-consequences`.
8. Watch CI until it is green.
