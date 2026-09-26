"""S02 Overture Buildings and S03a Overture Places.

Fetch: market ``path`` (GeoParquet) or a DuckDB query of the Overture S3 release for the study
area bbox [VERIFY V-13: release id; Places taxonomy fields]. Overture buildings already conflate
Microsoft ML footprints, so there is no separate Microsoft adapter (ADR-0018).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pandas as pd

from parkiq import units
from parkiq.ingest.base import IngestError, SourceAdapter, Standardized, study_area, to_analysis
from parkiq.store import WGS84

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)


def _duckdb_extract(url: str, bbox: Sequence[float], columns: str, out: Path) -> Path:
    """Write the bbox subset of an Overture theme to GeoParquet with DuckDB (cached)."""
    if out.exists() and out.stat().st_size > 0:
        return out
    import duckdb

    minx, miny, maxx, maxy = bbox
    con = duckdb.connect()
    try:
        for ext in ("spatial", "httpfs"):
            con.execute(f"INSTALL {ext}; LOAD {ext};")
        con.execute("SET s3_region='us-west-2';")
        out.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"""
            COPY (
              SELECT {columns}, geometry
              FROM read_parquet('{url}', filename=true, hive_partitioning=1)
              WHERE bbox.xmin <= {maxx} AND bbox.xmax >= {minx}
                AND bbox.ymin <= {maxy} AND bbox.ymax >= {miny}
            ) TO '{out.as_posix()}' (FORMAT PARQUET);
        """)
    except Exception as exc:  # duckdb raises its own hierarchy
        out.unlink(missing_ok=True)
        raise IngestError(f"Overture extract failed ({url}): {exc}") from exc
    finally:
        con.close()
    return out


def _read_overture(path: Path) -> gpd.GeoDataFrame:
    try:
        return gpd.read_parquet(path)
    except ValueError:
        # plain parquet with WKB geometry column
        df = pd.read_parquet(path)
        return gpd.GeoDataFrame(df, geometry=gpd.GeoSeries.from_wkb(df["geometry"]), crs=WGS84)


def _jsonable(v: Any) -> Any:
    if hasattr(v, "tolist"):
        v = v.tolist()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    return v


def _flat_raw(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Nested Overture structs → JSON text so the snapshot can go in a GeoPackage."""
    g = g.copy()
    for c in g.columns:
        if c != g.geometry.name and g[c].dtype == object:
            g[c] = g[c].map(
                lambda v: (
                    json.dumps(_jsonable(v), default=str)
                    if isinstance(v, dict | list | tuple) or hasattr(v, "tolist")
                    else v
                )
            )
    return g


class _OvertureBase(SourceAdapter):
    theme_columns: str = "id"

    def fetch(self, ctx: RunContext) -> Any:
        if self.entry.path is not None:
            return super().fetch(ctx)
        if not self.entry.vintage:
            raise IngestError(
                f"{self.source_id}: set sources.{self.source_id}.vintage to an "
                "Overture release id (e.g. 2026-09-17.0) [VERIFY]"
            )
        bbox = tuple(study_area(ctx).to_crs(WGS84).total_bounds)
        url = self.render_url(self.entry.url or "", ctx)
        return _duckdb_extract(
            url,
            bbox,
            self.theme_columns,
            self.cache_dir(ctx) / f"{self.source_id}.parquet",
        )


class OvertureBuildingsAdapter(_OvertureBase):
    """S02 buildings → Buildings (bldg_id, area_sqft, height_m, levels)."""

    source_id = "S02"
    theme_columns = "id, height, num_floors, sources"
    downstream_effect = "no Buildings, floor-area anchors and improvement checks degrade"

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        g = _read_overture(Path(raw))
        a, native, transf = to_analysis(g, ctx)
        a = a[a.geom_type.isin(["Polygon", "MultiPolygon"])]
        out = gpd.GeoDataFrame(
            {
                "bldg_id": a["id"].astype(str),
                "height_m": pd.to_numeric(a.get("height"), errors="coerce"),
                "levels": pd.to_numeric(a.get("num_floors"), errors="coerce"),
            },
            geometry=a.geometry,
            crs=a.crs,
        )
        out["area_sqft"] = out.geometry.area.map(lambda x: units.crs_area_to_sqft(x, ctx.cfg.crs))
        out = out.drop_duplicates("bldg_id").sort_values("bldg_id").reset_index(drop=True)
        return Standardized(
            "Raw_Buildings",
            _flat_raw(g[g.intersects(study_area(ctx).to_crs(g.crs).union_all())]),
            {"Buildings": out},
            native,
            transf,
        )


class OverturePlacesAdapter(_OvertureBase):
    """S03a places → Places (place_id ``ovt:<id>``, name, category)."""

    source_id = "S03a"
    theme_columns = "id, names, categories, confidence, brand, sources"
    downstream_effect = "no Overture POIs, demand anchors rely on OSM only"

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        g = _read_overture(Path(raw))
        a, native, transf = to_analysis(g, ctx)

        def _get(v: Any, key: str) -> Any:
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    return None
            return v.get(key) if isinstance(v, dict) else None

        min_conf = self.entry.options.get("min_confidence")
        notes = []
        if min_conf is not None:
            before = len(a)
            a = a[pd.to_numeric(a["confidence"], errors="coerce") >= float(min_conf)]
            notes.append(f"dropped {before - len(a)} places below confidence {min_conf}")
        pts = a.geometry.where(a.geom_type == "Point", a.geometry.representative_point())
        out = gpd.GeoDataFrame(
            {
                "place_id": "ovt:" + a["id"].astype(str),
                "name": a["names"].map(lambda v: _get(v, "primary")),
                "category": a["categories"].map(lambda v: _get(v, "primary")),
                "category_src": "overture",
                "tags_json": [
                    json.dumps(
                        {
                            "confidence": _jsonable(c),
                            "alternate": _jsonable(_get(cat, "alternate")),
                        },
                        default=str,
                    )
                    for c, cat in zip(a["confidence"], a["categories"], strict=True)
                ],
            },
            geometry=pts,
            crs=a.crs,
        )
        out = out.drop_duplicates("place_id").sort_values("place_id").reset_index(drop=True)
        return Standardized(
            "Raw_Places_Overture", _flat_raw(g), {"Places": out}, native, transf, notes
        )
