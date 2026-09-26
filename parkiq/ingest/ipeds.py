"""S12b, IPEDS directory (HD) points + enrollment (EFFY) [VERIFY V-19]."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pandas as pd

from parkiq.ingest.base import IngestError, download
from parkiq.ingest.tables import _csv, _TableAdapter, read_any

if TYPE_CHECKING:
    from parkiq.runner import RunContext


class IpedsAdapter(_TableAdapter):
    """S12b, IPEDS directory (HD) points + enrollment (EFFY) [VERIFY V-19].

    ``options.enrollment_path`` (or ``enrollment_url``) is joined on UNITID;
    ``options.enrollment_field`` names the total column and ``options.enrollment_filter``
    (column: value) selects the all-students row.
    """

    source_id = "S12b"
    target, raw_layer, id_field = "Institutions", "Raw_Institutions", "unitid"
    required = ("unitid", "name")
    optional = ("enrollment",)
    downstream_effect = "no university anchors"

    def fetch(self, ctx: RunContext) -> Any:
        hd = super().fetch(ctx)
        o = self.entry.options
        if o.get("enrollment_path"):
            ef = Path(o["enrollment_path"])
        elif o.get("enrollment_url"):
            ef = download(self.render_url(o["enrollment_url"], ctx), self.cache_dir(ctx))
        else:
            raise IngestError("S12b needs options.enrollment_path or enrollment_url")
        return (hd, ef)

    def load(self, raw: Any) -> gpd.GeoDataFrame:
        hd, ef = raw
        g = read_any(Path(hd), self.entry.options, self.source_id)
        o = self.entry.options
        e = (
            read_any(Path(ef), {**o, "x": None}, self.source_id)
            if Path(ef).suffix.lower() not in (".csv", ".zip")
            else _csv(Path(ef))
        )
        for col, val in (o.get("enrollment_filter") or {}).items():
            e = e[e[col].astype(str) == str(val)]
        fld = o.get("enrollment_field")
        if not fld:
            raise IngestError("S12b: set options.enrollment_field (e.g. EFYTOTLT) [VERIFY]")
        key = self.entry.field_map.get("unitid", "UNITID")
        e = e[[key, fld]].rename(columns={fld: "_enrollment"})
        e["_enrollment"] = pd.to_numeric(e["_enrollment"], errors="coerce")
        g[key] = g[key].astype(str)
        e[key] = e[key].astype(str)
        g = g.merge(e.drop_duplicates(key), on=key, how="left")
        g["enrollment"] = g["_enrollment"]
        return g.drop(columns=["_enrollment"])
