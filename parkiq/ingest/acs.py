"""S05 — ACS 5-year block groups via the Census Data API + TIGER block-group polygons.

Variables [VERIFY V-15 — table/variable IDs and vintage]:

* B01003_001E total population
* B08301_001E workers 16+; B08301_002E car, truck, or van (drove alone + carpooled)
* B25024_001E housing units; B25024_006E..009E units in 5–9 / 10–19 / 20–49 / 50+ structures
* B25044_001E occupied units; B25044_003E owner no vehicle; B25044_010E renter no vehicle

``drive_share = B08301_002E / B08301_001E`` is residence-based (commute of residents).
ADR-0014 notes a workplace-based share is preferable for job anchors; that is an M4 decision.
Counties queried = those intersecting the StudyArea (from the setup step), or
``options.counties`` (5-digit GEOIDs). Local override: ``path`` = CSV with ``GEOID`` + the
variables, and ``options.geometry_path`` = block-group polygons.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from parkiq.ingest.base import (
    HTTP_TIMEOUT_S,
    IngestError,
    SourceAdapter,
    Standardized,
    download,
    read_vector,
    redact,
    to_analysis,
)

if TYPE_CHECKING:
    from parkiq.runner import RunContext

VARS = [
    "B01003_001E",
    "B08301_001E",
    "B08301_002E",
    "B25024_001E",
    "B25024_006E",
    "B25024_007E",
    "B25024_008E",
    "B25024_009E",
    "B25044_001E",
    "B25044_003E",
    "B25044_010E",
]


def study_counties(ctx: RunContext) -> list[str]:
    """County GEOIDs intersecting the study area (setup summary) or options.counties."""
    from parkiq.runner import read_run_log

    opt = ctx.cfg.sources["S05"].options.get("counties")
    if opt:
        return [str(c) for c in opt]
    got = read_run_log(ctx)["steps"].get("setup", {}).get("summary", {}).get("study_counties")
    if not got:
        raise IngestError(
            "S05: study counties unknown (custom boundary?) — set "
            "sources.S05.options.counties to 5-digit county GEOIDs"
        )
    return list(got)


class AcsAdapter(SourceAdapter):
    """ACS block groups → BlockGroups."""

    source_id = "S05"
    downstream_effect = "no residential demand or local drive share"

    def fetch(self, ctx: RunContext) -> Any:
        """Return (table_csv_path, [geometry paths])."""
        opts = self.entry.options
        cdir = self.cache_dir(ctx)
        counties = (
            study_counties(ctx) if self.entry.path is None or not opts.get("geometry_path") else []
        )
        if self.entry.path is not None:
            table = Path(
                self.entry.path if not isinstance(self.entry.path, list) else self.entry.path[0]
            )
        else:
            table = cdir / "acs_bg.csv"
            if not table.exists():
                key = os.environ.get(opts.get("api_key_env", ""), "")
                frames = []
                for c in counties:
                    params = {
                        "get": "NAME," + ",".join(VARS),
                        "for": "block group:*",
                        "in": f"state:{c[:2]} county:{c[2:]}",
                    }
                    if key:
                        params["key"] = key
                    try:
                        r = requests.get(
                            self.render_url(self.entry.url or "", ctx),
                            params=params,
                            timeout=HTTP_TIMEOUT_S,
                        )
                        r.raise_for_status()
                        if "missing_key" in r.url or "invalid_key" in r.url:
                            env = opts.get("api_key_env")
                            raise IngestError(
                                "S05: the Census Data API requires an API key (it redirected to "
                                f"{redact(r.url)}). Set the environment variable {env}."
                            )
                        rows = r.json()
                    except (requests.RequestException, ValueError) as exc:
                        # never chain the original: its message can contain the key (ADR-0057)
                        raise IngestError(
                            redact(f"S05 Census API failed for county {c}: {exc}")
                        ) from None
                    frames.append(pd.DataFrame(rows[1:], columns=rows[0]))
                df = pd.concat(frames, ignore_index=True)
                df["GEOID"] = df["state"] + df["county"] + df["tract"] + df["block group"]
                df.to_csv(table, index=False)
        if opts.get("geometry_path"):
            geoms = [Path(opts["geometry_path"])]
        else:
            states = sorted({c[:2] for c in counties})
            geoms = [
                download(self.render_url(opts["geometry_url"], ctx, state_fips=s), cdir)
                for s in states
            ]
        return (table, geoms)

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        table, geoms = raw
        df = pd.read_csv(table, dtype={"GEOID": str})
        missing = [v for v in VARS if v not in df.columns]
        if missing:
            raise IngestError(f"S05 table missing {missing}")
        for v in VARS:  # ACS annotation sentinels (e.g. -666666666) → null
            df[v] = pd.to_numeric(df[v], errors="coerce")
            df.loc[df[v] < 0, v] = np.nan
        g = pd.concat([read_vector(p) for p in geoms], ignore_index=True)
        gcol = next(c for c in g.columns if c.upper() in ("GEOID", "GEOID20", "GEOIDFQ"))
        g = gpd.GeoDataFrame(
            g[[gcol, "geometry"]].rename(columns={gcol: "GEOID"}), geometry="geometry", crs=g.crs
        )
        g["GEOID"] = g["GEOID"].astype(str).str[-12:]
        m = g.merge(df, on="GEOID", how="inner")
        a, native, transf = to_analysis(m, ctx)
        u5 = a[["B25024_006E", "B25024_007E", "B25024_008E", "B25024_009E"]].sum(
            axis=1, min_count=1
        )
        workers = a["B08301_001E"]
        out = (
            gpd.GeoDataFrame(
                {
                    "bg_geoid": a["GEOID"],
                    "population": a["B01003_001E"],
                    "workers_total": workers,
                    "workers_drove": a["B08301_002E"],
                    "drive_share": (a["B08301_002E"] / workers.where(workers > 0)),
                    "units_total": a["B25024_001E"],
                    "units_5plus": u5,
                    "households": a["B25044_001E"],
                    "households_no_vehicle": a[["B25044_003E", "B25044_010E"]].sum(
                        axis=1, min_count=1
                    ),
                },
                geometry=a.geometry,
                crs=a.crs,
            )
            .sort_values("bg_geoid")
            .reset_index(drop=True)
        )
        return Standardized(
            "Raw_ACS_BG", m, {"BlockGroups": out}, native, transf, [f"{len(out)} block groups"]
        )
