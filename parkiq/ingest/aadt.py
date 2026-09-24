"""S13 — state DOT AADT counts [VERIFY V-20 layer + field names]."""

from __future__ import annotations

from typing import TYPE_CHECKING

import geopandas as gpd
import pandas as pd

from parkiq.ingest.tables import _TableAdapter

if TYPE_CHECKING:
    from parkiq.runner import RunContext


class AadtAdapter(_TableAdapter):
    """S13 — state DOT AADT counts [VERIFY V-20 layer + field names]."""

    source_id = "S13"
    target, raw_layer = "TrafficCounts", "Raw_AADT"
    required = ("count_id", "aadt")
    optional = ("year", "road")
    downstream_effect = "C08 access score has no AADT component"

    def shape(self, a: gpd.GeoDataFrame, ctx: RunContext) -> gpd.GeoDataFrame:
        a = a.copy()
        a["count_id"] = a["count_id"].astype(str)
        a["aadt"] = pd.to_numeric(a["aadt"], errors="coerce")
        if "year" in a.columns:
            a["year"] = pd.to_numeric(a["year"], errors="coerce")
        return a
