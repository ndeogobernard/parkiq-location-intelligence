"""S15 — EPA FRS / ACRES sites [VERIFY V-22]. ``options.brownfield_programs`` lists the"""

from __future__ import annotations

from typing import TYPE_CHECKING

import geopandas as gpd
import pandas as pd

from parkiq.ingest.base import IngestError
from parkiq.ingest.tables import _TableAdapter

if TYPE_CHECKING:
    from parkiq.runner import RunContext


class EpaAdapter(_TableAdapter):
    """S15 — EPA FRS / ACRES sites [VERIFY V-22]. ``options.brownfield_programs`` lists the
    program values that count as brownfield (method choice)."""

    source_id = "S15"
    target, raw_layer = "EnvSites", "Raw_EPA_Sites"
    required = ("site_id",)
    optional = ("name", "program", "brownfield_flag")
    downstream_effect = "no brownfield flags on candidates"

    def shape(self, a: gpd.GeoDataFrame, ctx: RunContext) -> gpd.GeoDataFrame:
        a = a.copy()
        progs = self.entry.options.get("brownfield_programs")
        if progs is None:
            raise IngestError(
                "S15: set options.brownfield_programs (list of program values "
                "that count as brownfield, e.g. [ACRES])"
            )
        prog = a["program"].astype(str) if "program" in a.columns else pd.Series("", index=a.index)
        a["brownfield_flag"] = prog.str.upper().map(lambda p: any(x.upper() in p for x in progs))
        return a
