"""S04, LEHD LODES WAC (jobs by census block and NAICS sector) [VERIFY V-14].

Block locations come from the LODES geography crosswalk's internal points (``blklatdd``,
``blklondd``), so no statewide block shapefile is needed. Sector → anchor-category mapping is M4
(``configs/anchor_crosswalk.yaml``, ADR-0022); here we keep all 20 CNS columns in ``sectors_json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pandas as pd

from parkiq.ingest.base import (
    IngestError,
    SourceAdapter,
    Standardized,
    download,
    points_from_xy,
    to_analysis,
)

if TYPE_CHECKING:
    from parkiq.runner import RunContext

SECTORS = [f"CNS{i:02d}" for i in range(1, 21)]


class LodesAdapter(SourceAdapter):
    """LODES WAC + crosswalk → BlockJobs."""

    source_id = "S04"
    downstream_effect = "no employment anchors, office/jobs demand missing"

    def fetch(self, ctx: RunContext) -> Any:
        """Return (wac_path, xwalk_path)."""
        opts = self.entry.options
        wac = super().fetch(ctx)
        if opts.get("xwalk_path"):
            xw = Path(opts["xwalk_path"])
            if not xw.exists():
                raise IngestError(f"S04 xwalk_path not found: {xw}")
        elif opts.get("xwalk_url"):
            xw = download(self.render_url(opts["xwalk_url"], ctx), self.cache_dir(ctx))
        else:
            raise IngestError("S04 needs options.xwalk_path or options.xwalk_url")
        return (wac, xw)

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        wac_p, xw_p = raw
        wac = pd.read_csv(wac_p, dtype={"w_geocode": str})
        xw = pd.read_csv(
            xw_p,
            dtype={"tabblk2020": str},
            usecols=lambda c: c in ("tabblk2020", "blklatdd", "blklondd"),
        )
        need = {"w_geocode", "C000", *SECTORS}
        if not need <= set(wac.columns):
            raise IngestError(f"S04 WAC missing columns {sorted(need - set(wac.columns))}")
        if not {"tabblk2020", "blklatdd", "blklondd"} <= set(xw.columns):
            raise IngestError("S04 crosswalk needs tabblk2020, blklatdd, blklondd")
        m = wac.merge(xw, left_on="w_geocode", right_on="tabblk2020", how="left")
        unloc = int(m["blklatdd"].isna().sum())
        pts = points_from_xy(m, "blklondd", "blklatdd")
        a, native, transf = to_analysis(pts, ctx)
        out = (
            gpd.GeoDataFrame(
                {
                    "block_geoid": a["w_geocode"].astype(str),
                    "jobs_total": a["C000"].astype(float),
                    "sectors_json": a[SECTORS].apply(
                        lambda r: json.dumps({k: int(r[k]) for k in SECTORS}), axis=1
                    ),
                },
                geometry=a.geometry,
                crs=a.crs,
            )
            .sort_values("block_geoid")
            .reset_index(drop=True)
        )
        raw_snap = pts[
            pts.geometry.intersects(ctx.store.read_layer("StudyArea").to_crs(4326).union_all())
        ]
        notes = [f"{len(out)} blocks, {int(out['jobs_total'].sum())} jobs in study area"]
        if unloc:
            notes.append(f"{unloc} WAC blocks had no crosswalk location (dropped)")
        return Standardized("Raw_LODES_WAC", raw_snap, {"BlockJobs": out}, native, transf, notes)
