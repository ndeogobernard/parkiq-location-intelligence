"""Units, study area, H3 grid tiling, slope, walk minutes."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from parkiq import units
from parkiq.setup import build_hex_grid, build_study_area, slope_percent


def test_crs_units() -> None:
    assert units.crs_unit_kind("EPSG:32617") == "m"
    assert units.crs_unit_kind("EPSG:3735") == "ft"  # Ohio South, US survey ft
    assert units.crs_unit_to_m("EPSG:3735") == pytest.approx(0.3048006096, rel=1e-9)
    with pytest.raises(ValueError):
        units.crs_unit_to_m("EPSG:4326")


def test_area_conversions() -> None:
    assert units.crs_area_to_sqft(1.0, "EPSG:32617") == pytest.approx(10.76391, rel=1e-6)
    # 1 ftUS² → ft² (international) is 1.000004
    assert units.crs_area_to_sqft(1.0, "EPSG:3735") == pytest.approx(1.000004, rel=1e-6)
    assert units.crs_area_to_km2(1e6, "EPSG:32617") == 1.0


def test_walk_minutes() -> None:
    # manual §2.3: 1.3 m/s = 78 m/min → 390 m in 5 minutes
    assert units.walk_minutes(390.0, 1.3) == pytest.approx(5.0)
    with pytest.raises(ValueError):
        units.walk_minutes(10, 0)


def test_study_area_buffer_in_feet_crs() -> None:
    b = gpd.GeoDataFrame(geometry=[box(0, 0, 10_000, 10_000)], crs="EPSG:3735")
    s = build_study_area(b, 1.0)
    # 1 mile in US survey feet ≈ 5279.989
    grow = s.total_bounds[2] - 10_000
    assert grow == pytest.approx(1609.344 / 0.3048006096, rel=1e-6)


def test_hex_grid_tiles_without_gaps_or_overlaps() -> None:
    sa = gpd.GeoDataFrame(geometry=[box(400_000, 4_650_000, 403_000, 4_653_000)], crs="EPSG:32617")
    h = build_hex_grid(sa, 9)
    assert h["hex_id"].is_unique
    total = h.geometry.area.sum()
    union = h.geometry.union_all()
    assert total - union.area == pytest.approx(0.0, abs=1e-6 * total)  # no overlaps
    assert all(len(p.interiors) == 0 for p in getattr(union, "geoms", [union]))  # no gaps
    assert h["area_km2"].mean() == pytest.approx(0.105, rel=0.1)  # H3 r9 average
    # centroid rule: every hex centre lies in the study area
    assert h.geometry.centroid.within(sa.union_all().buffer(1)).all()


def test_slope_percent_on_plane() -> None:
    x = np.arange(50, dtype=float)
    dem = np.tile(x * 0.05 * 10, (50, 1))  # rises 0.5 m per 10 m cell → 5 %
    s = slope_percent(dem, 10.0, 10.0, 1.0, None)
    assert np.nanmedian(s) == pytest.approx(5.0, rel=1e-9)
    assert np.isnan(s[0, 0])  # edges are NaN (Horn window incomplete)
    # metres of elevation on a US-feet grid: z factor 1/0.3048006 keeps the ratio
    s_ft = slope_percent(dem, 10.0 / 0.3048006096, 10.0 / 0.3048006096, 1 / 0.3048006096, None)
    assert np.nanmedian(s_ft) == pytest.approx(5.0, rel=1e-6)


def test_slope_nodata_propagates() -> None:
    dem = np.zeros((5, 5), dtype="float32")
    dem[2, 2] = -9999
    s = slope_percent(dem, 1, 1, 1.0, -9999)
    assert np.isnan(s[1:4, 1:4]).all()


def test_hex_grid_fills_enclosed_hole() -> None:
    """Franklin case: the centroid rule dropped one cell whose 6 neighbours were all in."""
    import h3

    outer = box(400_000, 4_650_000, 403_000, 4_653_000)
    sa0 = gpd.GeoDataFrame(geometry=[outer], crs="EPSG:32617")
    ref = build_hex_grid(sa0, 9)
    victim = ref.iloc[len(ref) // 2]
    c = victim.geometry.centroid
    # a tiny pocket around one hex centre (stand-in for a narrow inlet tip)
    sa = gpd.GeoDataFrame(geometry=[outer.difference(c.buffer(30))], crs="EPSG:32617")
    h = build_hex_grid(sa, 9)
    assert h.attrs["filled_holes"] == 1
    assert victim["hex_id"] in set(h["hex_id"])
    assert set(h["hex_id"]) == set(ref["hex_id"])
    union = h.geometry.union_all()
    assert all(len(p.interiors) == 0 for p in getattr(union, "geoms", [union]))
    assert all(n in set(h["hex_id"]) for n in h3.grid_disk(victim["hex_id"], 1))
