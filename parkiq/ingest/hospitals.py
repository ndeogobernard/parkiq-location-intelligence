"""S12a — hospitals with beds [VERIFY V-18 source]."""

from __future__ import annotations

from typing import TYPE_CHECKING

import geopandas as gpd
import pandas as pd

from parkiq.ingest.tables import _TableAdapter

if TYPE_CHECKING:
    from parkiq.runner import RunContext


class HospitalsAdapter(_TableAdapter):
    """S12a — hospitals with beds [VERIFY V-18 source]."""

    source_id = "S12a"
    target, raw_layer, id_field = "Hospitals", "Raw_Hospitals", "hospital_id"
    required = ("hospital_id", "name", "beds")
    downstream_effect = "no medical anchors by bed count"

    def shape(self, a: gpd.GeoDataFrame, ctx: RunContext) -> gpd.GeoDataFrame:
        a = a.copy()
        a["beds"] = pd.to_numeric(a["beds"], errors="coerce")
        a.loc[a["beds"] < 0, "beds"] = None  # HIFLD uses -999 for unknown
        a["geometry"] = a.geometry.where(a.geom_type == "Point", a.geometry.representative_point())
        return a
