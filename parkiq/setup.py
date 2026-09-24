"""Phase A — market setup (SCOPE §5.1; tool 2 ``SetupMarket``).

Named ``setup.py`` because SCOPE §6.2 names it so. It is NOT a setuptools script — packaging is
``pyproject.toml``.

Writes: MarketBoundary, StudyArea, Submarkets, HexGrid, WalkNodes, WalkEdges, Slope_pct (GeoTIFF),
and registry rows for S00 (boundary), S08 (network), S18 (DEM).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from shapely.geometry import Polygon, mapping

from parkiq import network, qaqc, units
from parkiq.ingest.base import IngestError, download, read_vector, register_source
from parkiq.runner import RunContext, register
from parkiq.store import WGS84

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- boundary


def resolve_boundary(ctx: RunContext) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame | None, str]:
    """Load the market boundary as one dissolved polygon in EPSG:4326.

    Returns:
        (boundary in 4326 with ``name, geoid``; all counties in 4326 or None; endpoint text)

    Raises:
        IngestError: If the boundary cannot be found or is ambiguous.
    """
    m = ctx.cfg.market.market
    b = m.boundary
    if b.type == "custom":
        g = read_vector(b.value)
        if g.crs is None:
            raise IngestError(f"custom boundary {b.value} has no CRS")
        geom = g.to_crs(WGS84).union_all()
        out = gpd.GeoDataFrame({"name": [m.name], "geoid": [None]}, geometry=[geom], crs=WGS84)
        return out, None, f"local: {b.value}"

    s00 = ctx.cfg.sources["S00"]
    if b.type == "county":
        src = s00.path if s00.path is not None else _tiger(ctx, s00.url or "", "county")
    else:  # place
        tmpl = s00.options.get("place_url")
        if s00.options.get("place_path"):
            src = Path(s00.options["place_path"])
        elif tmpl:
            src = _tiger(ctx, tmpl, "place", state_fips=b.value[:2])
        else:
            raise IngestError(
                "boundary.type=place needs sources.S00.options.place_url or place_path"
            )
    counties_or_places = read_vector(src if not isinstance(src, list) else src[0])
    geoid_col = next((c for c in counties_or_places.columns if c.upper() == "GEOID"), None)
    if geoid_col is None:
        raise IngestError(f"{src}: no GEOID column")
    hit = counties_or_places[counties_or_places[geoid_col].astype(str) == b.value]
    if len(hit) != 1:
        raise IngestError(f"Expected 1 feature with GEOID {b.value} in {src}, found {len(hit)}")
    geom = hit.to_crs(WGS84).union_all()
    out = gpd.GeoDataFrame({"name": [m.name], "geoid": [b.value]}, geometry=[geom], crs=WGS84)
    counties = counties_or_places.to_crs(WGS84) if b.type == "county" else None
    return out, counties, str(src)


def _tiger(ctx: RunContext, template: str, kind: str, **extra: Any) -> Path:
    s00 = ctx.cfg.sources["S00"]
    if not s00.vintage:
        raise IngestError("sources.S00.vintage (TIGER year) must be set to download the boundary")
    url = template.format(year=s00.vintage, **extra)
    dest = ctx.cache_dir / "S00" / s00.vintage
    dest.mkdir(parents=True, exist_ok=True)
    return download(url, dest)


def build_study_area(boundary_a: gpd.GeoDataFrame, buffer_miles: float) -> gpd.GeoDataFrame:
    """Boundary + buffer (analysis CRS), dissolved.

    Args:
        boundary_a: Boundary in the analysis CRS.
        buffer_miles: Buffer distance in statute miles (SCOPE §2.2).

    Returns:
        One-row GeoDataFrame with ``buffer_miles, area_sqmi``.
    """
    crs = boundary_a.crs
    dist = units.m_to_crs(units.miles_to_m(buffer_miles), crs)
    geom = boundary_a.union_all().buffer(dist)
    sqmi = units.crs_area_to_km2(geom.area, crs) * 1e6 / units.M_PER_MILE**2
    return gpd.GeoDataFrame(
        {"buffer_miles": [buffer_miles], "area_sqmi": [sqmi]}, geometry=[geom], crs=crs
    )


# --------------------------------------------------------------------------- H3 grid


def _cells_to_gdf(cells: list[str], crs: Any) -> gpd.GeoDataFrame:
    polys = [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in cells]
    return gpd.GeoDataFrame({"hex_id": cells}, geometry=polys, crs=WGS84).to_crs(crs)


def build_hex_grid(study_a: gpd.GeoDataFrame, resolution: int) -> gpd.GeoDataFrame:
    """H3 cells whose centres fall in the study area, plus enclosed holes, in the analysis CRS.

    H3 polyfill uses centroid containment, the same rule as the manual (§4.2 step 2). At a narrow
    concave inlet of the study-area edge that rule can exclude a cell whose neighbours are all
    included, leaving an enclosed hole; SCOPE §4.5 requires HexGrid without gaps, so cells inside
    any hole of the grid's union are added (ADR-0009). ``grid.attrs["filled_holes"]`` counts them.

    Args:
        study_a: StudyArea in the analysis CRS.
        resolution: H3 resolution (SCOPE §2.2: 9).

    Returns:
        GeoDataFrame with ``hex_id, area_km2`` (analysis CRS), sorted by ``hex_id``.
    """
    crs = study_a.crs
    geom4326 = study_a.to_crs(WGS84).union_all()
    cells = set(h3.geo_to_cells(mapping(geom4326), resolution))
    g = _cells_to_gdf(sorted(cells), crs)
    union = g.geometry.union_all()
    holes = [Polygon(r) for p in getattr(union, "geoms", [union]) for r in p.interiors]
    added: set[str] = set()
    for hole in holes:
        h4326 = gpd.GeoSeries([hole], crs=crs).to_crs(WGS84).iloc[0]
        added |= set(h3.geo_to_cells(mapping(h4326), resolution)) - cells
    if added:
        log.info("HexGrid: filled %d enclosed hole cell(s) left by the centroid rule", len(added))
        g = _cells_to_gdf(sorted(cells | added), crs)
    g["area_km2"] = g.geometry.area.map(lambda a: units.crs_area_to_km2(a, crs))
    g.attrs["filled_holes"] = len(added)
    return g


def assign_submarkets(hexes: gpd.GeoDataFrame, subs: gpd.GeoDataFrame | None) -> pd.Series:
    """Submarket name by largest overlap (manual §4.2 step 3); null where none."""
    if subs is None or subs.empty:
        return pd.Series([None] * len(hexes), index=hexes.index, dtype="object")
    inter = gpd.overlay(
        hexes[["hex_id", "geometry"]],
        subs[["name", "geometry"]],
        how="intersection",
        keep_geom_type=True,
    )
    inter["a"] = inter.geometry.area
    best = inter.sort_values("a", ascending=False).drop_duplicates("hex_id")
    return hexes["hex_id"].map(best.set_index("hex_id")["name"])


# --------------------------------------------------------------------------- slope


def slope_percent(
    dem: np.ndarray, cell_x: float, cell_y: float, z_to_xy: float, nodata: float | None
) -> np.ndarray:
    """Percent slope with Horn's (1981) 3×3 method (as ArcGIS/GDAL ``slope -p``).

    Args:
        dem: Elevation grid.
        cell_x: Cell width in CRS units.
        cell_y: Cell height in CRS units (positive).
        z_to_xy: Factor converting elevation units to CRS units (e.g. m → ftUS = 3.2808...).
        nodata: DEM nodata value.

    Returns:
        float32 grid of percent rise; NaN on edges and where any neighbour is nodata.
    """
    z = dem.astype("float64") * z_to_xy
    if nodata is not None:
        z[dem == nodata] = np.nan
    p = np.pad(z, 1, constant_values=np.nan)
    a, b, c = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    d, f = p[1:-1, :-2], p[1:-1, 2:]
    g, h, i = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * cell_x)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * cell_y)
    out = np.sqrt(dzdx**2 + dzdy**2) * 100.0
    out[np.isnan(z)] = np.nan  # Horn ignores the centre cell; a nodata centre stays nodata
    return out.astype("float32")


def build_slope(ctx: RunContext, study_a: gpd.GeoDataFrame) -> dict[str, Any]:
    """DEM (S18) → reprojected mosaic → percent slope GeoTIFF ``rasters/Slope_pct.tif``."""
    import rasterio
    from rasterio.merge import merge
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    from parkiq.ingest.dem import DemAdapter

    s18 = ctx.cfg.sources["S18"]
    adapter = DemAdapter(s18)
    ok, why = adapter.is_enabled(ctx)
    if not ok:
        log.warning(
            "S18 DEM not configured (%s) — effect: no Slope_pct; the screen's slope "
            "filter cannot run",
            why,
        )
        register_source(ctx, "S18", s18, status="not configured", row_count=0, notes=why)
        return {"slope": "not configured"}
    tiles = adapter.fetch(ctx)
    tile_paths = tiles if isinstance(tiles, list) else [tiles]
    srcs = [rasterio.open(p) for p in tile_paths]
    try:
        dem_crs = srcs[0].crs
        bounds = study_a.to_crs(dem_crs).total_bounds
        mosaic, mtrans = merge(srcs, bounds=tuple(bounds))
        nodata = srcs[0].nodata
        z_unit = adapter.z_unit_m(srcs[0])
    finally:
        for s in srcs:
            s.close()
    src_arr = mosaic[0]
    h_, w_ = src_arr.shape
    left, top = mtrans.c, mtrans.f
    right, bottom = left + mtrans.a * w_, top + mtrans.e * h_
    dst_crs = ctx.cfg.crs.to_wkt()
    trans, w, h = calculate_default_transform(dem_crs, dst_crs, w_, h_, left, bottom, right, top)
    fill = -9999.0 if nodata is None else float(nodata)
    dst = np.full((h, w), fill, dtype="float32")
    reproject(
        src_arr,
        dst,
        src_transform=mtrans,
        src_crs=dem_crs,
        src_nodata=nodata,
        dst_transform=trans,
        dst_crs=dst_crs,
        dst_nodata=fill,
        resampling=Resampling.bilinear,
    )
    z_to_xy = z_unit / units.crs_unit_to_m(ctx.cfg.crs)
    slope = slope_percent(dst, trans.a, -trans.e, z_to_xy, fill)
    out = ctx.rasters_dir / "Slope_pct.tif"
    prof = {
        "driver": "GTiff",
        "height": h,
        "width": w,
        "count": 1,
        "dtype": "float32",
        "crs": dst_crs,
        "transform": trans,
        "nodata": np.nan,
        "compress": "deflate",
        "tiled": True,
    }
    with rasterio.open(out, "w", **prof) as ds:
        ds.write(slope, 1)
        ds.update_tags(units="percent rise", method="Horn 3x3", source="S18", run_id=ctx.run_id)
    ctx.store.register_raster("Slope_pct", out)
    register_source(
        ctx,
        "S18",
        s18,
        status="loaded",
        row_count=len(tile_paths),
        endpoint=adapter.entry_endpoint(),
        native_crs=str(dem_crs),
        transformation=f"{dem_crs} -> {ctx.cfg.crs.to_string()} bilinear; z factor {z_to_xy:.6f}",
    )
    valid = slope[np.isfinite(slope)]
    return {
        "slope_cells": int(valid.size),
        "slope_p95": float(np.percentile(valid, 95)) if valid.size else None,
    }


# --------------------------------------------------------------------------- step


@register(
    "setup",
    deps=("schema",),
    reads=(
        "market.market",
        "market.study",
        "market.network",
        "sources.S00",
        "sources.S08",
        "sources.S18",
    ),
)
def setup_market(ctx: RunContext) -> dict[str, Any]:
    """Tool 2 SetupMarket: boundary, study area, submarkets, H3 grid, walk network, slope."""
    cfg = ctx.cfg
    crs = cfg.crs
    boundary4326, counties, endpoint = resolve_boundary(ctx)
    boundary = boundary4326.to_crs(crs)
    boundary["area_sqmi"] = boundary.geometry.area.map(
        lambda a: units.crs_area_to_km2(a, crs) * 1e6 / units.M_PER_MILE**2
    )
    ctx.store.write_layer("Raw_Boundary", boundary4326, "S00")
    ctx.store.write_layer("MarketBoundary", boundary, "S00")
    s00 = cfg.sources["S00"]
    if cfg.market.market.boundary.type == "custom":
        s00 = s00.model_copy(
            update={
                "provider": "Market config",
                "license": "per file",
                "dataset": "Custom boundary polygon",
                "verify": False,
            }
        )
    register_source(
        ctx,
        "S00",
        s00,
        status="loaded",
        row_count=1,
        endpoint=endpoint,
        native_crs="EPSG:4326 (after read)",
        transformation=f"-> {crs.to_string()}",
    )

    study = build_study_area(boundary, cfg.market.study.buffer_miles)
    ctx.store.write_layer("StudyArea", study, "DERIVED")

    study_counties: list[str] = []
    if counties is not None:
        geoid_col = next(c for c in counties.columns if c.upper() == "GEOID")
        hit = counties[counties.intersects(study.to_crs(WGS84).union_all())]
        study_counties = sorted(hit[geoid_col].astype(str))

    subs = None
    ss = cfg.market.market.submarkets_source
    if ss is not None:
        raw = read_vector(ss.path).to_crs(crs)
        subs = gpd.GeoDataFrame(
            {
                "name": raw[ss.name_field].astype(str),
                "type": raw[ss.type_field].astype(str) if ss.type_field else None,
            },
            geometry=raw.geometry,
            crs=crs,
        )
        wanted = set(cfg.market.market.focus_submarkets)
        unknown = wanted - set(subs["name"])
        if unknown:
            raise IngestError(f"focus_submarkets not found in {ss.path}: {sorted(unknown)}")
        subs = subs[subs["name"].isin(wanted)] if wanted else subs
        ctx.store.write_layer("Submarkets", subs, "CONFIG")

    hexes = build_hex_grid(study, cfg.market.study.h3_resolution)
    hexes["submarket"] = assign_submarkets(hexes, subs)
    ctx.store.write_layer("HexGrid", hexes, "DERIVED")

    nodes, edges, net_info = network.build_walk_network(ctx, study)
    ctx.store.write_layer("WalkNodes", nodes, "S08")
    ctx.store.write_layer("WalkEdges", edges, "S08")
    register_source(
        ctx,
        "S08",
        cfg.sources["S08"],
        status="loaded",
        row_count=len(edges),
        endpoint=net_info["endpoint"],
        native_crs=net_info["native_crs"],
        transformation=net_info["transformation"],
        notes=net_info["notes"],
    )

    slope_info = build_slope(ctx, study)

    qa = qaqc.check_setup(ctx, boundary, study, hexes, nodes, edges)
    if qa:
        raise RuntimeError(f"SetupMarket: {qa} error-level QA checks failed — see QAQC_Log")
    return {
        "boundary_area_sqmi": round(float(boundary["area_sqmi"].iloc[0]), 3),
        "study_area_sqmi": round(float(study["area_sqmi"].iloc[0]), 3),
        "study_counties": study_counties,
        "hex_count": len(hexes),
        "hex_filled_holes": int(hexes.attrs.get("filled_holes", 0)),
        "hex_mean_area_km2": round(float(hexes["area_km2"].mean()), 5),
        "walk_nodes": len(nodes),
        "walk_edges": len(edges),
        **slope_info,
    }
