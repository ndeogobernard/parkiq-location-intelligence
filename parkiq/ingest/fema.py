"""S14 — FEMA NFHL flood hazard zones [VERIFY V-21 floodway encoding]."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pandas as pd

from parkiq.ingest.base import Standardized
from parkiq.ingest.tables import _TableAdapter

if TYPE_CHECKING:
    from parkiq.runner import RunContext


class FemaAdapter(_TableAdapter):
    """S14 — FEMA NFHL flood hazard zones [VERIFY V-21 floodway encoding].

    ``floodway_flag`` = ZONE_SUBTY contains "FLOODWAY"; ``sfha_flag`` = SFHA_TF == "T".
    """

    source_id = "S14"
    target, raw_layer = "FloodHazard", "Raw_FEMA_NFHL"
    required = ("fld_zone",)
    optional = ("zone_subty", "sfha_flag", "floodway_flag")
    downstream_effect = "floodway screen cannot run (parcels marked Review)"

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        if not self.entry.field_map:
            self.entry = self.entry.model_copy(
                update={
                    "field_map": {
                        "fld_zone": "FLD_ZONE",
                        "zone_subty": "ZONE_SUBTY",
                        "sfha_tf": "SFHA_TF",
                    }
                }
            )
        return super().standardize(raw, ctx)

    def shape(self, a: gpd.GeoDataFrame, ctx: RunContext) -> gpd.GeoDataFrame:
        a = a[a.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        sub = (
            a["zone_subty"].fillna("").astype(str)
            if "zone_subty" in a.columns
            else pd.Series("", index=a.index)
        )
        a["floodway_flag"] = sub.str.upper().str.contains("FLOODWAY")
        a["sfha_flag"] = (
            (a["sfha_tf"].astype(str).str.upper() == "T") if "sfha_tf" in a.columns else None
        )
        return a
