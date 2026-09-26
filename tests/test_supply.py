"""M3 supply: dissolve, dedupe rules (ADR-0020), capacity, private share, allocation.

Geometries here are small SYNTHETIC test shapes (tests only), not market data.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pyproj import CRS
from shapely.geometry import LineString, Point, box

from parkiq.allocation import WalkGraph, allocate, band_weight
from parkiq.supply import (
    capacity,
    dedupe,
    dissolve_adjacent,
    norm_name,
    osm_facilities,
    private_flags,
    similarity,
)

FT = CRS.from_epsg(3735)


def _osm(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    base = {"osm_id": None, "name": None, "parking": None, "capacity": None, "fee": None,
            "access": None, "operator": None, "levels": None, "area_sqft": None}  # fmt: skip
    geoms = [r.pop("geometry") for r in rows]
    df = pd.DataFrame([{**base, **r} for r in rows])
    df["osm_id"] = [f"way/{i}" for i in range(len(df))]
    f, _ = osm_facilities(gpd.GeoDataFrame(df, geometry=geoms, crs=FT))
    f["parts"] = 1
    return f


def test_names() -> None:
    assert norm_name("  Lot #5 & Garage ") == "lot 5 and garage"
    assert similarity("columbus commons garage", "garage columbus commons") == 1.0
    assert similarity("lot 5", "lot 6") == 0.0  # numbered lots are different facilities
    assert similarity("lot 5", "Lot 5 north".lower()) == 1.0
    assert similarity(None, "x") == 0.0


def test_dissolve_touching_same_facility_only() -> None:
    f = _osm([
        {"parking": "surface", "name": "Alpha Lot", "geometry": box(0, 0, 100, 100)},
        {"parking": "surface", "geometry": box(100, 0, 200, 100)},          # touches, unnamed
        {"parking": "surface", "name": "Beta Lot", "geometry": box(200, 0, 300, 100)},  # other name
        {"parking": "multi-storey", "geometry": box(0, 100, 100, 200)},     # touches, other type
    ])  # fmt: skip
    out = dissolve_adjacent(f, FT)
    # unnamed middle piece joins Alpha; Beta stays separate (would make 2 names); garage separate
    assert len(out) == 3
    alpha = out[out["name"] == "Alpha Lot"].iloc[0]
    assert alpha["parts"] == 2 and alpha.geometry.area == pytest.approx(20000)


def test_dedupe_rules() -> None:
    f = _osm([
        {"parking": "surface", "name": "Main St Garage Lot", "geometry": box(0, 0, 100, 100)},
        {"parking": "surface", "name": "Main Street Garage Lot",
         "geometry": Point(200, 50)},                       # named, ~30 m away, similar -> merge
        {"parking": "surface", "geometry": Point(400, 50)},  # unnamed, 91 m away -> no merge
        {"parking": "surface", "geometry": Point(50, 50)},   # unnamed, inside polygon -> merge
        {"parking": "multi-storey", "geometry": Point(60, 60)},  # unnamed, other type -> no merge
    ])  # fmt: skip
    out, st = dedupe(f, FT, dist_m=40, touch_m=5, threshold=0.80)
    assert len(out) == 3
    assert st == {"merged_named_pairs": 1, "merged_unnamed_pairs": 1}


def test_capacity_and_private() -> None:
    f = _osm([
        {"parking": "surface", "geometry": box(0, 0, 320, 100), "access": "customers"},
        {"parking": "surface", "capacity": "50", "fee": "yes", "geometry": box(500, 0, 600, 100)},
        {"parking": "multi-storey", "levels": "4", "geometry": box(0, 500, 100, 600)},
        {"parking": "multi-storey", "geometry": box(500, 500, 600, 600)},  # levels unknown
        {"parking": None, "geometry": Point(900, 900)},
    ])  # fmt: skip
    c = capacity(f, None, stall_sqft=320, efficiency=0.9, crs=FT)
    assert c.loc[0, "capacity_est"] == 90 and c.loc[0, "capacity_source"] == "area"
    assert c.loc[1, "capacity_final"] == 50 and c.loc[1, "capacity_source"] == "stated"
    assert c.loc[2, "capacity_est"] == pytest.approx(125) and c.loc[2, "capacity_source"] == (
        "footprint x levels"
    )
    assert np.isnan(c.loc[3, "capacity_final"]) and np.isnan(c.loc[4, "capacity_final"])
    priv = private_flags(c, unknown_private=True)
    assert list(priv) == [True, False, True, True, True]


def test_band_weights() -> None:
    w = band_weight(np.array([1.0, 3.0, 4.0, 8.0, 8.5]), [3, 5, 8], {3: 1.0, 5: 0.6, 8: 0.25})
    assert list(w) == [1.0, 1.0, 0.6, 0.25, 0.0]


def test_allocation_conserves() -> None:
    # a straight street of 5 nodes, 400 ft apart; hexes = squares around each node
    xs = [0, 400, 800, 1200, 1600]
    nodes = gpd.GeoDataFrame({"node_id": [str(i) for i in range(5)]},
                             geometry=[Point(x, 0) for x in xs], crs=FT)  # fmt: skip
    speed = 1.3
    mins = 400 * 0.3048 / speed / 60
    edges = gpd.GeoDataFrame(
        {"u": [str(i) for i in range(4)], "v": [str(i + 1) for i in range(4)],
         "walk_minutes": [mins] * 4},
        geometry=[LineString([(xs[i], 0), (xs[i + 1], 0)]) for i in range(4)], crs=FT,
    )  # fmt: skip
    hexes = gpd.GeoDataFrame(
        {"hex_id": [f"h{i}" for i in range(5)]},
        geometry=[box(x - 200, -200, x + 200, 200) for x in xs],
        crs=FT,
    )
    g = WalkGraph.from_layers(nodes, edges, FT, speed)
    pts = gpd.GeoDataFrame(geometry=[Point(0, 0), Point(1600, 0)], crs=FT)
    out, st = allocate(pts, np.array([100.0, 40.0]), hexes, g, [3, 5, 8], {3: 1.0, 5: 0.6, 8: 0.25})
    assert out.sum() == pytest.approx(140.0) and st["outside_grid_dropped"] == 0
    one, _ = allocate(pts.iloc[:1], np.array([100.0]), hexes, g, [3, 5, 8],
                      {3: 1.0, 5: 0.6, 8: 0.25})  # fmt: skip
    w = np.array([1.0, 1.0, 0.6, 0.6, 0.25])  # 0, 1.6, 3.1, 4.7, 6.3 min
    assert list(one.round(6)) == list((100 * w / w.sum()).round(6))


def test_survey_selection_quota_and_spacing() -> None:
    from parkiq.survey import select_sample

    fac = gpd.GeoDataFrame(
        {"facility_id": [f"F{i}" for i in range(8)],
         "name": [f"lot {i}" for i in range(8)], "operator": [None] * 8,
         "type": ["Garage", "Garage"] + ["Surface"] * 5 + ["Garage"],
         "fee_flag": [True, True, True, False, True, False, False, True],
         "capacity_stated": [500, 400, 50, 60, 70, 80, 90, 300], "capacity_est": [None] * 8,
         "capacity_source": ["stated"] * 8, "submarket": ["A"] * 7 + ["B"],
         "source_ids": [f"way/{i}" for i in range(8)]},
        geometry=[Point(i * 1000, 0) for i in range(7)] + [Point(0, 5000)], crs=FT,
    )  # fmt: skip
    fac.loc[1, "geometry"] = Point(100, 0)  # garage 1 is 30 m from garage 0 -> skipped
    s = select_sample(fac, [{"label": "A", "areas": ["A"], "n": 3, "garages": 1}], 150, 2)
    smp = s[s.role == "sample"]
    assert len(smp) == 3 and (smp["type"] == "Garage").sum() == 1
    assert "F1" not in set(s["facility_id"]) and len(s[s.role == "backup"]) == 2
    assert set(s["area"]) == {"A"}


@pytest.mark.slow
def test_supply_step_on_fixture(m1_run) -> None:  # type: ignore[no-untyped-def]
    from parkiq.runner import run_steps

    run_steps(m1_run, ["supply"])
    hs = m1_run.store.read_table("Hex_Supply_Daypart")
    fac = m1_run.store.read_layer("SupplyFacilities")
    assert len(fac) > 0 and set(hs["daypart"]) == {"wd_day", "wd_eve", "we_day", "we_eve", "event"}
    one = hs[hs["daypart"] == "wd_day"]
    assert (one["effective_supply_stalls"] <= one["supply_stalls"] + 1e-9).all()
