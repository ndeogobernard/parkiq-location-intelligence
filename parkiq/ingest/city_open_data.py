"""S23 / S23b / S23c — municipal zoning from city open data (SCOPE §3, S20–S24).

* S23  base zoning districts (ArcGIS REST layer) → ``ZoningDistricts``
* S23b commercial + planning overlays (one or two REST layers) → ``ZoningOverlays``, each coded
  to the zoning table's overlay keys (``overlay:UCO``, ``overlay:University/NC``)
* S23c downtown parking zones A/B (local GeoPackage; Franklin: derived from City Code Map 2,
  ADR-0061) → ``ParkingZones``

Everything market-specific is config: field maps, the overlay type → code map, the jurisdiction
name. :func:`assign_zoning` then puts zoning code, overlays and parking zone on every parcel and
resolves the zoning screen with :class:`parkiq.zoning.ZoningTable`.
"""

from __future__ import annotations

import logging
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from parkiq.ingest.arcgis_rest import query_to_geojson
from parkiq.ingest.base import IngestError, Standardized, read_vector, study_area
from parkiq.ingest.tables import _TableAdapter
from parkiq.store import WGS84
from parkiq.zoning import ZoningResult, ZoningTable

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)


def _jurisdiction(entry_options: dict[str, Any], source_id: str) -> str:
    j = entry_options.get("jurisdiction")
    if not j:
        raise IngestError(f"{source_id}: set options.jurisdiction (zoning-table jurisdiction name)")
    return str(j)


class ZoningDistrictsAdapter(_TableAdapter):
    """S23 — base zoning districts."""

    source_id = "S23"
    target, raw_layer = "ZoningDistricts", "Raw_Zoning"
    required = ("zoning_code",)
    optional = ("jurisdiction", "general_category", "zoning_status", "ord_no", "case_number")
    downstream_effect = "no zoning codes on parcels — every parcel's zoning screen is Review"

    def shape(self, a: gpd.GeoDataFrame, ctx: RunContext) -> gpd.GeoDataFrame:
        a = a[a.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        a["jurisdiction"] = _jurisdiction(self.entry.options, self.source_id)
        a["zoning_code"] = a["zoning_code"].astype(str).str.strip()
        return a


class ZoningOverlaysAdapter(_TableAdapter):
    """S23b — overlays. ``options.type_codes`` maps the published type/name to a table key."""

    source_id = "S23b"
    target, raw_layer = "ZoningOverlays", "Raw_ZoningOverlays"
    required = ("overlay_code",)
    optional = ("overlay_name", "overlay_type", "jurisdiction", "ord_no")
    downstream_effect = "overlay rules (UCO/CCO/RCO design rule, University NC/RC) not applied"

    def fetch(self, ctx: RunContext) -> Any:
        first = super().fetch(ctx)
        extra = self.entry.options.get("planning_overlays_url")
        if not extra or self.entry.path is not None:
            return first
        bbox = tuple(study_area(ctx).to_crs(WGS84).total_bounds)
        second = query_to_geojson(
            extra, bbox, self.cache_dir(ctx) / f"{self.source_id}_planning.geojson"
        )
        return [first, second]

    def load(self, raw: Any) -> gpd.GeoDataFrame:
        paths = raw if isinstance(raw, list) else [raw]
        o = self.entry.options
        frames = []
        for i, p in enumerate(paths):
            g = read_vector(Path(p))
            if i == 0:  # commercial overlays: code from the type
                codes = o.get("type_codes") or {}
                tf, nf = o.get("type_field", "TYPE"), o.get("name_field", "OVRLY_NAME")
                g["overlay_type"] = g[tf].astype(str)
                g["overlay_name"] = g[nf].astype(str)
                g["overlay_code"] = g["overlay_type"].map(codes)
                unmapped = sorted(set(g.loc[g["overlay_code"].isna(), "overlay_type"]))
                if unmapped:
                    raise IngestError(f"S23b: overlay types without options.type_codes: {unmapped}")
            else:  # planning overlays: code from the name
                pf = o.get("planning_name_field", "OVERLAY_NAME")
                g["overlay_type"] = "PLANNING OVERLAY"
                g["overlay_name"] = g[pf].astype(str).str.strip()
                g["overlay_code"] = "overlay:" + g["overlay_name"]
            if "ORD_NO" in g.columns:
                g = g.rename(columns={"ORD_NO": "ord_no"})  # GPKG names are case-insensitive
            # GeoPackage column names are case-insensitive: drop source columns that collide with
            # the derived lower-case ones (e.g. OVERLAY_NAME vs overlay_name)
            derived = {"overlay_code", "overlay_type", "overlay_name", "ord_no"}
            g = g.drop(columns=[c for c in g.columns if c not in derived and c.lower() in derived])
            frames.append(g)
        crs = frames[0].crs
        return gpd.GeoDataFrame(
            pd.concat([f.to_crs(crs) for f in frames], ignore_index=True), crs=crs
        )

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        if not self.entry.field_map:  # codes are built in load(); identity map
            self.entry = self.entry.model_copy(update={"field_map": {}})
        return super().standardize(raw, ctx)

    def shape(self, a: gpd.GeoDataFrame, ctx: RunContext) -> gpd.GeoDataFrame:
        a = a[a.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        a["jurisdiction"] = _jurisdiction(self.entry.options, self.source_id)
        return a


class ParkingZonesAdapter(_TableAdapter):
    """S23c — downtown parking zones (local GeoPackage layer, ``options.layer``)."""

    source_id = "S23c"
    target, raw_layer = "ParkingZones", "Raw_ParkingZones"
    required = ("zone",)
    optional = ("jurisdiction", "method", "derived_date")
    downstream_effect = "Downtown (DD) parcels cannot be placed in Zone A/B — routed to Review"

    def load(self, raw: Any) -> gpd.GeoDataFrame:
        p = Path(raw if not isinstance(raw, list) else raw[0])
        layer = self.entry.options.get("layer")
        return gpd.read_file(p, layer=layer) if layer else read_vector(p)

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        if not self.entry.field_map:
            self.entry = self.entry.model_copy(update={"field_map": {}})
        return super().standardize(raw, ctx)

    def shape(self, a: gpd.GeoDataFrame, ctx: RunContext) -> gpd.GeoDataFrame:
        a = a.copy()
        a["jurisdiction"] = _jurisdiction(self.entry.options, self.source_id)
        a["zone"] = a["zone"].astype(str).str.upper()
        return a


# --------------------------------------------------------------------------- parcel join


def largest_overlap(parcels: gpd.GeoDataFrame, zones: gpd.GeoDataFrame, col: str) -> pd.Series:
    """Value of ``zones[col]`` with the largest intersection area per parcel (NaN if none)."""
    j = gpd.sjoin(
        parcels[["geometry"]], zones[[col, "geometry"]], how="inner", predicate="intersects"
    )
    if j.empty:
        return pd.Series(np.nan, index=parcels.index, dtype="object")
    counts = j.index.value_counts()
    single = j[j.index.isin(counts[counts == 1].index)][col]
    multi = j[j.index.isin(counts[counts > 1].index)]
    if len(multi):
        area = shapely.area(
            shapely.intersection(
                parcels.geometry.loc[multi.index].values,
                zones.geometry.loc[multi["index_right"]].values,
            )
        )
        m = multi.assign(_a=area).reset_index(names="_pid")
        best = m.sort_values(["_pid", "_a"], ascending=[True, False]).drop_duplicates("_pid")
        single = pd.concat([single, best.set_index("_pid")[col]])
    return single.reindex(parcels.index)


def assign_zoning(
    parcels: gpd.GeoDataFrame,
    table: ZoningTable,
    districts: gpd.GeoDataFrame | None,
    overlays: gpd.GeoDataFrame | None,
    parking: gpd.GeoDataFrame | None,
    review_ft: float,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """Zoning code (largest overlap), overlays, parking zone and zoning screen per parcel.

    Only parcels whose ``jurisdiction`` matches the zoning layer's jurisdiction get its codes;
    every other parcel resolves through the table's ``*`` row (Unknown → Review).

    Returns:
        (parcels with zoning columns, summary counts)
    """
    p = parcels.copy()
    for c in ("zoning_code", "zoning_overlays", "parking_zone"):
        p[c] = None
    p["parking_zone_near_boundary"] = False
    stats: dict[str, Any] = {}
    if districts is not None and len(districts):
        jur = str(districts["jurisdiction"].iloc[0])
        inj = p["jurisdiction"].astype(str).str.lower() == jur.lower()
        codes = largest_overlap(p.loc[inj], districts, "zoning_code")
        p.loc[inj, "zoning_code"] = codes
        stats["zoned"] = int(codes.notna().sum())
        stats["in_jurisdiction_unzoned"] = int(codes.isna().sum())
    pts = gpd.GeoDataFrame(geometry=p.geometry.representative_point(), crs=p.crs)
    if overlays is not None and len(overlays):
        j = gpd.sjoin(pts, overlays[["overlay_code", "geometry"]], predicate="within")
        ov = j.groupby(level=0)["overlay_code"].agg(lambda s: ";".join(sorted(set(s))))
        p.loc[ov.index, "zoning_overlays"] = ov
        stats["with_overlay"] = len(ov)
    if parking is not None and len(parking):
        j = gpd.sjoin(pts, parking[["zone", "geometry"]], predicate="within")
        pz = j[~j.index.duplicated()]["zone"]
        p.loc[pz.index, "parking_zone"] = pz
        zones = {z: g.union_all() for z, g in parking.groupby("zone")}
        for z, other in (("A", zones.get("B")), ("B", zones.get("A"))):
            if other is None:
                continue
            idx = p.index[p["parking_zone"] == z]
            d = p.geometry.loc[idx].distance(other)
            p.loc[idx, "parking_zone_near_boundary"] = (d <= review_ft).to_numpy()
        stats["in_parking_zone"] = len(pz)
        stats["near_zone_boundary"] = int(p["parking_zone_near_boundary"].sum())

    @cache
    def _res(
        j: str | None, code: str | None, ovs: str | None, pz: str | None, near: bool
    ) -> ZoningResult:
        is_dd = code is not None and code.replace("-", "").upper() == "DD"
        return table.resolve(
            j,
            code,
            overlays=ovs.split(";") if ovs else None,
            parking_zone=pz if is_dd else None,
            near_zone_boundary=near and is_dd,
        )

    res = [
        _res(
            None if pd.isna(j) else str(j),
            None if pd.isna(c) else str(c),
            None if pd.isna(o) else str(o),
            None if pd.isna(z) else str(z),
            bool(n),
        )
        for j, c, o, z, n in zip(
            p["jurisdiction"],
            p["zoning_code"],
            p["zoning_overlays"],
            p["parking_zone"],
            p["parking_zone_near_boundary"],
            strict=True,
        )
    ]
    p["zoning_screen"] = [r.zoning_screen for r in res]
    p["zoning_status"] = [r.route for r in res]
    p["zoning_reason"] = [r.reason for r in res]
    stats["zoning_status"] = p["zoning_status"].value_counts().to_dict()
    return p, stats


def load_table(entry_options: dict[str, Any]) -> ZoningTable | None:
    """The market zoning table named in S23 ``options.zoning_table_path`` (None if unset)."""
    path = entry_options.get("zoning_table_path")
    if not path:
        return None
    return ZoningTable.load(path, entry_options.get("code_aliases") or {})


__all__ = [
    "ParkingZonesAdapter",
    "ZoningDistrictsAdapter",
    "ZoningOverlaysAdapter",
    "assign_zoning",
    "load_table",
]
