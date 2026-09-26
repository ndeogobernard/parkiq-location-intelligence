"""M4 demand and gap: categories, campus rule, building shares, hot-zone components.

Geometries are small SYNTHETIC test shapes (tests only), not market data.
"""

from __future__ import annotations

import geopandas as gpd
import h3
import pytest
from pyproj import CRS
from shapely.geometry import Point, box

from parkiq.demand import building_share, campus_parcels, norm_owner, place_category
from parkiq.gap import components

FT = CRS.from_epsg(3735)
RULES = [
    {"category": "Hotel", "match": {"tourism": ["hotel", "motel"]}},
    {"category": "RestaurantBar", "match": {"amenity": ["restaurant", "bar"]}},
    {"category": "Retail", "match": {"shop": "*"}},
]


def test_place_category() -> None:
    assert place_category("tourism=hotel", RULES) == "Hotel"
    assert place_category("shop=clothes", RULES) == "Retail"
    assert place_category("amenity=bar", RULES) == "RestaurantBar"
    assert place_category("leisure=sports_centre", RULES) is None
    assert place_category("nonsense", RULES) is None


def test_building_share_splits_footprint() -> None:
    pts = gpd.GeoDataFrame(geometry=[Point(10, 10), Point(20, 20), Point(500, 500)], crs=FT)
    b = gpd.GeoDataFrame({"area_sqft": [10000.0], "levels": [3.0], "height_m": [10.0]},
                         geometry=[box(0, 0, 100, 100)], crs=FT)  # fmt: skip
    share, levels, _height = building_share(pts, b)
    assert list(share[:2]) == [5000.0, 5000.0] and share.isna().iloc[2]
    assert levels.iloc[0] == 3.0


def test_campus_grows_over_same_owner_only() -> None:
    parcels = gpd.GeoDataFrame(
        {"owner": ["OHIO STATE UNIVERSITY", "Ohio State University.", "SMITH JOHN",
                   "OHIO STATE UNIVERSITY"]},
        geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100), box(200, 0, 300, 100),
                  box(1000, 0, 1100, 100)], crs=FT,
    )  # fmt: skip
    assert norm_owner("Ohio State University.") == "OHIO STATE UNIVERSITY"
    c = campus_parcels(parcels, Point(50, 50))
    assert c is not None and c.area == pytest.approx(20000)  # not Smith, not the detached parcel
    assert campus_parcels(parcels, Point(5000, 5000)) is None


def test_hot_zone_components() -> None:
    a = h3.latlng_to_cell(39.96, -83.0, 9)
    ring = [h for h in h3.grid_disk(a, 1) if h != a]
    far = h3.latlng_to_cell(40.10, -82.8, 9)
    comps = components([a, ring[0], far])
    sizes = sorted(len(c) for c in comps)
    assert sizes == [1, 2]


@pytest.mark.slow
def test_demand_and_gap_on_fixture(m1_run) -> None:  # type: ignore[no-untyped-def]
    from parkiq.runner import run_steps

    run_steps(m1_run, ["supply", "demand", "gap"])
    d = m1_run.store.read_table("Hex_Demand_Daypart")
    a = m1_run.store.read_layer("DemandAnchors")
    for dp in ("wd_day", "wd_eve"):
        assert d[d.daypart == dp]["demand_stalls"].sum() == pytest.approx(
            a[f"demand_{dp}"].sum(), rel=0.02
        )
    assert "Office" in set(a["category"])
    g = m1_run.store.read_table("Hex_Gap_Daypart")
    assert len(g) > 0
