"""Point/attribute-table sources configured entirely by ``field_map`` + ``options``:
S10 venues (events.py), S12a hospitals, S12b IPEDS, S13 AADT, S14 FEMA NFHL, S15 EPA — each
in its own module; this module holds the shared reader and base class.

For CSV/XLSX inputs, ``options.x`` / ``options.y`` name the coordinate columns and
``options.xy_crs`` their CRS (required — no silent default).
Vector inputs (shp/gpkg/geojson) carry their own CRS. ArcGIS REST ``url``s (S13, S14) are queried
for the study-area bbox.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pandas as pd

from parkiq.ingest.arcgis_rest import query_to_geojson
from parkiq.ingest.base import (
    IngestError,
    SourceAdapter,
    Standardized,
    apply_field_map,
    download,
    points_from_xy,
    read_vector,
    study_area,
    to_analysis,
)
from parkiq.store import WGS84

if TYPE_CHECKING:
    from parkiq.runner import RunContext


def read_any(path: Path, options: dict[str, Any], source_id: str) -> gpd.GeoDataFrame:
    """Read a CSV/XLSX (with x/y columns) or any vector file into a GeoDataFrame."""
    suf = path.suffix.lower()
    if suf == ".zip" and any(n.lower().endswith(".csv") for n in zipfile.ZipFile(path).namelist()):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            df = pd.read_csv(z.open(name), dtype=str, encoding_errors="replace")
        suf = ".csv"
    elif suf == ".csv":
        df = pd.read_csv(path, dtype=str, encoding_errors="replace")
    elif suf in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str)
    else:
        return read_vector(path)
    x, y, crs = options.get("x"), options.get("y"), options.get("xy_crs")
    if not (x and y and crs):
        raise IngestError(
            f"{source_id}: tabular input needs options.x, options.y and "
            "options.xy_crs (e.g. EPSG:4326)"
        )
    return points_from_xy(df, x, y, crs)


class _TableAdapter(SourceAdapter):
    target: str = ""
    raw_layer: str = ""
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    id_field: str = ""

    def fetch(self, ctx: RunContext) -> Any:
        if self.entry.path is not None:
            return super().fetch(ctx)
        url = self.render_url(self.entry.url or "", ctx)
        if "/MapServer/" in url or "/FeatureServer/" in url:
            bbox = tuple(study_area(ctx).to_crs(WGS84).total_bounds)
            o = self.entry.options
            return query_to_geojson(
                url,
                bbox,
                self.cache_dir(ctx) / f"{self.source_id}.geojson",
                where=o.get("where", "1=1"),
                page_size=int(o.get("page_size", 1000)),
                max_allowable_offset=o.get("max_allowable_offset"),
                geometry_precision=o.get("geometry_precision"),
            )
        return download(url, self.cache_dir(ctx))

    def load(self, raw: Any) -> gpd.GeoDataFrame:
        return read_any(
            Path(raw if not isinstance(raw, list) else raw[0]), self.entry.options, self.source_id
        )

    def shape(self, a: gpd.GeoDataFrame, ctx: RunContext) -> gpd.GeoDataFrame:
        """Hook for per-source derived fields."""
        return a

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        g = self.load(raw)
        m = apply_field_map(g, self.entry.field_map, list(self.required), self.source_id)
        a, native, transf = to_analysis(m, ctx)
        a = self.shape(a, ctx)
        cols = [c for c in (*self.required, *self.optional) if c in a.columns]
        out = gpd.GeoDataFrame(a[cols].copy(), geometry=a.geometry, crs=a.crs)
        if self.id_field:
            out[self.id_field] = out[self.id_field].astype(str)
            out = out.drop_duplicates(self.id_field).sort_values(self.id_field)
        out = out.reset_index(drop=True)
        raw_snap = g[g.intersects(study_area(ctx).to_crs(g.crs).union_all())] if g.crs else g
        return Standardized(
            self.raw_layer, raw_snap, {self.target: out}, native, transf, [f"{len(out)} features"]
        )


def _csv(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            return pd.read_csv(z.open(name), dtype=str, encoding_errors="replace")
    return pd.read_csv(path, dtype=str, encoding_errors="replace")
