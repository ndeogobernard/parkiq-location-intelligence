"""S06 OSM parking and S03b OSM POIs (via OSMnx ``features_from_polygon`` / Overpass).

Tag queries live in ``configs/sources.yaml`` (method choices, not code). A market ``path``
override is a GeoJSON/GPKG of OSM features with tag columns (e.g. an extract you made with
QuickOSM or osmium), which is also how the fixture runs offline.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import osmnx as ox
import pandas as pd

from parkiq import units
from parkiq.ingest.base import SourceAdapter, Standardized, read_vector, study_area, to_analysis
from parkiq.store import WGS84

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)

POI_KEEP_TAGS = [
    "capacity",
    "rooms",
    "beds",
    "seats",
    "building:levels",
    "cuisine",
    "brand",
    "operator",
    "opening_hours",
]


def _num(v: Any) -> float | None:
    """Parse a numeric OSM tag (``"120"``, ``"120;40"`` → 120, ``"approx 50"`` → 50)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    m = re.search(r"\d+(\.\d+)?", str(v))
    return float(m.group()) if m else None


def _osm_id(df: pd.DataFrame) -> pd.Series:
    if isinstance(df.index, pd.MultiIndex) and {"element", "id"} <= set(df.index.names):
        return pd.Series([f"{e}/{i}" for e, i in df.index], index=df.index)
    if "element" in df.columns and "id" in df.columns:
        return df["element"].astype(str) + "/" + df["id"].astype(str)
    if "osm_id" in df.columns:
        return df["osm_id"].astype(str)
    raise ValueError("OSM features need (element, id) or osm_id")


class _OsmBase(SourceAdapter):
    def fetch(self, ctx: RunContext) -> Any:
        if self.entry.path is not None:
            return read_vector(
                self.entry.path if not isinstance(self.entry.path, list) else self.entry.path[0]
            )
        cache = self.cache_dir(ctx) / f"{self.source_id}.gpkg"
        if cache.exists():
            return read_vector(cache)
        ox.settings.use_cache = True
        ox.settings.cache_folder = str(ctx.cache_dir / "osmnx_http")
        poly = study_area(ctx).to_crs(WGS84).union_all()
        tags = self.entry.options.get("tags", {})
        log.info("%s: querying Overpass for %s", self.source_id, tags)
        g = ox.features_from_polygon(poly, tags=tags)
        g = g.copy()
        g.insert(0, "osm_id", _osm_id(g))
        g = g.reset_index(drop=True)
        for c in g.columns:
            if c != g.geometry.name and g[c].dtype == object:
                g[c] = g[c].map(lambda v: json.dumps(v) if isinstance(v, list | dict) else v)
        g.to_file(cache, engine="pyogrio")
        return g


class OsmParkingAdapter(_OsmBase):
    """S06 ``amenity=parking`` → ParkingOSM (supply merge happens in M3)."""

    source_id = "S06"
    downstream_effect = "no OSM parking, supply inventory depends on other sources only"

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        g: gpd.GeoDataFrame = raw.copy()
        if "osm_id" not in g.columns:
            g.insert(0, "osm_id", _osm_id(g))
        a, native, transf = to_analysis(g, ctx)
        if "amenity" in a.columns:
            a = a[a["amenity"] == "parking"]

        def col(c: str) -> pd.Series:
            return a[c] if c in a.columns else pd.Series([None] * len(a), index=a.index)

        levels = col("parking:levels").map(_num).fillna(col("building:levels").map(_num))
        area = a.geometry.area.where(a.geom_type.isin(["Polygon", "MultiPolygon"]))
        out = gpd.GeoDataFrame(
            {
                "osm_id": a["osm_id"].astype(str),
                "name": col("name"),
                "parking": col("parking"),
                "capacity": col("capacity").map(_num),
                "fee": col("fee"),
                "access": col("access"),
                "operator": col("operator"),
                "levels": levels,
                "area_sqft": area.map(
                    lambda x: None if pd.isna(x) else units.crs_area_to_sqft(x, ctx.cfg.crs)
                ),
            },
            geometry=a.geometry,
            crs=a.crs,
        )
        out = out.drop_duplicates("osm_id").sort_values("osm_id").reset_index(drop=True)
        return Standardized(
            "Raw_OSM_Parking",
            g,
            {"ParkingOSM": out},
            native,
            transf,
            [f"{int(out['capacity'].notna().sum())} with capacity tag"],
        )


class OsmPoiAdapter(_OsmBase):
    """S03b POIs → Places (place_id ``osm:<element>/<id>``, category ``key=value``)."""

    source_id = "S03b"
    downstream_effect = "no OSM POIs, demand anchors rely on Overture only"

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        g: gpd.GeoDataFrame = raw.copy()
        if "osm_id" not in g.columns:
            g.insert(0, "osm_id", _osm_id(g))
        a, native, transf = to_analysis(g, ctx)
        tags: dict[str, Any] = self.entry.options.get("tags", {})

        def category(row: pd.Series) -> str | None:
            for k, vals in tags.items():
                v = row.get(k)
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                if vals is True or v in vals:
                    return f"{k}={v}"
            return None

        cats = a.apply(category, axis=1)
        a = a[cats.notna()]
        cats = cats[cats.notna()]
        pts = a.geometry.where(a.geom_type == "Point", a.geometry.representative_point())
        keep = [t for t in POI_KEEP_TAGS if t in a.columns]
        tag_json = (
            a[keep].apply(lambda r: json.dumps({k: r[k] for k in keep if pd.notna(r[k])}), axis=1)
            if keep
            else pd.Series(["{}"] * len(a), index=a.index)
        )
        out = gpd.GeoDataFrame(
            {
                "place_id": "osm:" + a["osm_id"].astype(str),
                "name": a["name"] if "name" in a.columns else None,
                "category": cats,
                "category_src": "osm",
                "tags_json": tag_json,
            },
            geometry=pts,
            crs=a.crs,
        )
        # polygons kept whole at the edge can put their point outside: clip the points again
        inside = out.within(study_area(ctx).union_all())
        notes = [f"{int((~inside).sum())} edge features with their point outside StudyArea dropped"]
        out = out[inside]
        out = out.drop_duplicates("place_id").sort_values("place_id").reset_index(drop=True)
        return Standardized("Raw_OSM_POI", g, {"Places": out}, native, transf, notes)
