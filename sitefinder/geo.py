"""Place points (businesses, MRT exits, hawker centres) in URA planning areas."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape

from .sources import RAW


class PlanningAreas:
    def __init__(self, path: Path | None = None):
        g = json.loads((path or RAW / "planning_areas.geojson").read_text(encoding="utf-8"))
        self.names = [f["properties"]["PLN_AREA_N"].upper() for f in g["features"]]
        self.regions = [f["properties"].get("REGION_N", "") for f in g["features"]]
        # Drop any Z coordinate; planning areas are 2-D.
        self.shapes = [shapely.force_2d(shape(f["geometry"])) for f in g["features"]]
        self.tree = shapely.STRtree(self.shapes)

    def region_of(self) -> dict[str, str]:
        return dict(zip(self.names, self.regions))

    def locate(self, lng: np.ndarray, lat: np.ndarray) -> np.ndarray:
        """Planning area name for each point, or None if it falls outside every area
        (at sea, or a bad coordinate). Boundary points go to the first area that covers them."""
        points = shapely.points(np.asarray(lng, dtype=float), np.asarray(lat, dtype=float))
        point_idx, area_idx = self.tree.query(points, predicate="intersects")
        out = np.full(len(points), None, dtype=object)
        seen = set()
        for p, a in zip(point_idx, area_idx):
            if p not in seen:
                out[p] = self.names[a]
                seen.add(p)
        return out

    def locate_frame(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(self.locate(df["lng"].to_numpy(), df["lat"].to_numpy()), index=df.index)
