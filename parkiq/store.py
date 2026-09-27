"""GeoPackage storage: layers, attribute tables, rasters, registries.

See docs/ARCHITECTURE.md §3 and ADR-0010/0011. One self-contained GeoPackage per run (ADR-0010).
Idempotency (docs/ENGINEERING.md): a step deletes its own rows for the ``run_id`` and rewrites
them. Because a run's GeoPackage only ever holds that run, a spatial layer is rewritten whole;
shared attribute tables (QAQC_Log, DataSourceRegistry, ScoreRuns ...) delete
``WHERE run_id = ? AND <key>`` before appending.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio
from pyproj import CRS

from parkiq.schema import Schema, SchemaError, conform
from parkiq.schema_build import apply_constraints

log = logging.getLogger(__name__)

WGS84 = CRS.from_epsg(4326)
LAYER_REGISTRY = "_ParkIQ_Layers"


def utcnow() -> datetime:
    """Timezone-aware UTC now (used for load_ts)."""
    return datetime.now(UTC).replace(microsecond=0)


class Store:
    """Read/write access to one run's GeoPackage.

    Args:
        gpkg: Path to the run GeoPackage (created on first write).
        schema: Loaded schema.
        run_id: Run identifier stamped on every row.
        analysis_crs: Market analysis CRS.
    """

    def __init__(self, gpkg: Path, schema: Schema, run_id: str, analysis_crs: CRS) -> None:
        self.gpkg = Path(gpkg)
        self.schema = schema
        self.run_id = run_id
        self.crs = analysis_crs
        self.gpkg.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ helpers
    def exists(self) -> bool:
        """True once the GeoPackage file exists."""
        return self.gpkg.exists()

    def layers(self) -> list[str]:
        """Names of all layers/tables in the GeoPackage."""
        if not self.exists():
            return []
        return [str(r[0]) for r in pyogrio.list_layers(self.gpkg)]

    def has(self, name: str) -> bool:
        """True if the layer/table exists."""
        return name in self.layers()

    def _lineage(self, df: pd.DataFrame, source_id: str | None) -> pd.DataFrame:
        df = df.copy()
        if source_id is not None:
            df["source_id"] = source_id
        elif "source_id" not in df.columns:
            raise SchemaError("source_id not given and not present as a column")
        df["run_id"] = self.run_id
        df["load_ts"] = utcnow()
        return df

    def _register(self, name: str, kind: str, crs: str | None, path: str | None = None) -> None:
        ldef = self.schema.layers.get(name)
        fd = (
            ldef.feature_dataset
            if ldef
            else (self.schema.rasters.get(name, {}) or {}).get("feature_dataset")
        )
        geom = ldef.geometry if ldef else None
        row = pd.DataFrame(
            [
                {
                    "layer": name,
                    "kind": kind,
                    "feature_dataset": fd,
                    "geometry": geom,
                    "crs": crs,
                    "path": path,
                    "schema_version": self.schema.version,
                    "run_id": self.run_id,
                    "updated": utcnow().isoformat(),
                }
            ]
        )
        self._delete_where(LAYER_REGISTRY, {"layer": name})
        self._append_table(LAYER_REGISTRY, row)

    # ------------------------------------------------------------------ spatial layers
    def write_layer(self, name: str, gdf: gpd.GeoDataFrame, source_id: str | None) -> int:
        """Validate against the schema and (re)write a feature layer for this run.

        Args:
            name: Layer name (must be in schema.yaml).
            gdf: Features. CRS must equal the layer's declared CRS (analysis or EPSG:4326).
            source_id: Source ID for lineage (e.g. ``"S04"`` or ``"DERIVED"``); None when the
                frame already carries a per-row ``source_id`` (layers fed by several sources).

        Returns:
            Number of features written.

        Raises:
            SchemaError: On CRS mismatch or schema violations.
        """
        ldef = self.schema.layer(name)
        if not ldef.is_spatial:
            raise SchemaError(f"{name} is an attribute table; use write_table")
        want = WGS84 if ldef.crs == "wgs84" else self.crs
        if gdf.crs is None or not CRS.from_user_input(gdf.crs).equals(want):
            raise SchemaError(f"{name}: CRS {gdf.crs} != required {want.to_string()}")
        df = conform(self._lineage(gdf, source_id), ldef, self.schema, spatial=True)
        gdf2 = gpd.GeoDataFrame(df, geometry=gdf.geometry.name, crs=gdf.crs)
        # Raw layers may mix geometry types; declare generic geometry.
        gtype = None if ldef.geometry in ("Geometry", None) else ldef.geometry
        if len(gdf2) and gtype == "MultiPolygon":
            gdf2 = gdf2.set_geometry(gdf2.geometry.map(_to_multipolygon))
        pyogrio.write_dataframe(
            gdf2,
            self.gpkg,
            layer=name,
            driver="GPKG",
            geometry_type=gtype or "Unknown",
            promote_to_multi=False,
        )
        apply_constraints(self.gpkg, self.schema, [name])
        self._register(name, "features", want.to_string())
        log.info("wrote %s: %d features", name, len(gdf2))
        return len(gdf2)

    def written_layers(self) -> list[str]:
        """Layers/tables a step has written in this run (BuildSchema's empty layers excluded)."""
        if not self.has(LAYER_REGISTRY):
            return []
        return [str(x) for x in self.read_table(LAYER_REGISTRY)["layer"]]

    def read_layer(self, name: str, **kwargs: Any) -> gpd.GeoDataFrame:
        """Read a feature layer (optionally with pyogrio kwargs such as ``columns``)."""
        if not self.has(name):
            raise KeyError(f"Layer {name} not found in {self.gpkg}")
        return pyogrio.read_dataframe(self.gpkg, layer=name, **kwargs)

    # ------------------------------------------------------------------ attribute tables
    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.gpkg)

    def _delete_where(self, table: str, where: Mapping[str, Any]) -> int:
        if not self.has(table):
            return 0
        clause = " AND ".join(f'"{k}" = ?' for k in where)
        with closing(self._connect()) as con, con:
            cur = con.execute(f'DELETE FROM "{table}" WHERE {clause}', tuple(where.values()))
            return cur.rowcount

    def _append_table(self, table: str, df: pd.DataFrame) -> None:
        append = self.has(table)
        if append:
            with closing(self._connect()) as con:
                n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            # an empty table is replaced, not appended to: it may come from an older schema
            # version, or carry a column type GDAL inferred from an all-null first write
            append = n > 0
        pyogrio.write_dataframe(df, self.gpkg, layer=table, driver="GPKG", append=append)

    def write_table(self, name: str, df: pd.DataFrame, key: Mapping[str, Any] | None = None) -> int:
        """Replace this run's rows (optionally narrowed by ``key``) in an attribute table.

        Args:
            name: Table name in schema.yaml ``tables``.
            df: Rows to append (``run_id`` is set here).
            key: Extra equality filter for the delete, e.g. ``{"step": "ingest"}``.

        Returns:
            Rows written.
        """
        ldef = self.schema.layer(name)
        if ldef.is_spatial:
            raise SchemaError(f"{name} is a feature layer; use write_layer")
        d = df.copy()
        d["run_id"] = self.run_id
        allowed = {f.name for f in ldef.fields}
        extra = set(d.columns) - allowed
        if extra:
            raise SchemaError(f"{name}: columns not in schema: {sorted(extra)}")
        for f in ldef.fields:
            if f.name not in d.columns:
                d[f.name] = None
        d = d[[f.name for f in ldef.fields]]
        # conform() checks domains/types; tables carry run_id but no source_id/load_ts
        for f in ldef.fields:
            if f.domain:
                bad = d[f.name][~d[f.name].map(lambda v, dm=f.domain: self.schema.domain_ok(dm, v))]
                if len(bad):
                    raise SchemaError(f"{name}.{f.name}: values outside {f.domain}: {set(bad)}")
            if f.type == "BOOLEAN":
                d[f.name] = d[f.name].map(lambda v: None if v is None else int(bool(v)))
            elif f.type in ("TEXT", "JSON"):
                d[f.name] = d[f.name].map(
                    lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
                )
            elif f.type == "DATETIME":
                d[f.name] = d[f.name].map(lambda v: None if v is None else str(v))
            elif f.type == "REAL":
                d[f.name] = pd.to_numeric(d[f.name], errors="coerce").astype("float64")
            elif f.type == "INTEGER":
                d[f.name] = pd.to_numeric(d[f.name], errors="coerce").astype("Int64")
        self._delete_where(name, {"run_id": self.run_id, **(key or {})})
        if len(d):
            self._append_table(name, d)
            apply_constraints(self.gpkg, self.schema, [name])
        if not self.has(LAYER_REGISTRY) or name != LAYER_REGISTRY:
            self._register(name, "attributes", None)
        return len(d)

    def read_table(self, name: str) -> pd.DataFrame:
        """Read an attribute table (empty frame if absent)."""
        if not self.has(name):
            return pd.DataFrame()
        return pyogrio.read_dataframe(self.gpkg, layer=name, read_geometry=False)

    # ------------------------------------------------------------------ rasters
    def register_raster(self, name: str, path: Path) -> None:
        """Record a GeoTIFF stored beside the GeoPackage (ADR-0012)."""
        rel = path.relative_to(self.gpkg.parent) if path.is_relative_to(self.gpkg.parent) else path
        self._register(name, "raster", self.crs.to_string(), str(rel).replace("\\", "/"))


SLIVER_AREA = 1e-4  # CRS units²: polygon parts below this are clipping slivers (not a parameter)


def _to_multipolygon(geom: Any) -> Any:
    """MultiPolygon with sliver parts removed (ArcGIS rejects near-zero-area parts, ADR-0053)."""
    from shapely.geometry import MultiPolygon, Polygon

    if geom is None or geom.is_empty:
        return geom
    if isinstance(geom, Polygon):
        parts: list[Polygon] = [geom]
    elif isinstance(geom, MultiPolygon):
        parts = list(geom.geoms)
    else:  # GeometryCollection from make_valid: keep polygonal parts
        parts = []
        for g in getattr(geom, "geoms", []):
            if isinstance(g, MultiPolygon):
                parts.extend(g.geoms)
            elif isinstance(g, Polygon):
                parts.append(g)
    keep = [g for g in parts if g.area > SLIVER_AREA] or parts
    if not keep:
        return None
    if isinstance(geom, MultiPolygon) and len(keep) == len(parts):
        return geom
    return MultiPolygon(keep)
