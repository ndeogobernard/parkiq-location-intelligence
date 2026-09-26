"""M2 ingest: parcel options, owner overrides, zoning join, REST options, licensed stubs.

Frames built here are small SYNTHETIC test geometries (tests only), not market data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pytest
from pyproj import CRS
from shapely.geometry import box

from parkiq.ingest import arcgis_rest
from parkiq.ingest.base import IngestError
from parkiq.ingest.city_open_data import assign_zoning, largest_overlap
from parkiq.ingest.county_parcels import (
    apply_owner_overrides,
    join_jurisdiction,
    load_owner_overrides,
)
from parkiq.zoning import ZoningTable

REPO = Path(__file__).parents[1]
TABLE = ZoningTable.load(REPO / "markets" / "franklin_oh" / "zoning_screen.csv", {"RURAL": "R"})
FT = CRS.from_epsg(3735)


def _gdf(rows: list[dict[str, Any]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry=[r.pop("geometry") for r in rows], crs=FT)


def test_join_jurisdiction(tmp_path: Path) -> None:
    tbl = tmp_path / "td.csv"
    pd.DataFrame(
        {"CVTTXCD": ["1", "2", "3"], "City": ["COLUMBUS CITY", None, "DUBLIN CITY"],
         "Township": ["", "PRAIRIE TWP", ""]}
    ).to_csv(tbl, index=False)  # fmt: skip
    parcels = pd.DataFrame({"CVTTXCD": ["1", "2", "3", "9"]})
    spec = {"path": str(tbl), "key": "CVTTXCD", "name_field": "City",
            "fallback_field": "Township", "rename": {"COLUMBUS CITY": "Columbus"}}  # fmt: skip
    j, miss = join_jurisdiction(parcels, spec)
    assert list(j[:3]) == ["Columbus", "PRAIRIE TWP", "DUBLIN CITY"] and miss == 1


def test_owner_overrides_win_after_rules(tmp_path: Path) -> None:
    csv = tmp_path / "o.csv"
    csv.write_text(
        "owner_name_pattern,owner_type,note\n^NEW PAR\\b,Corporate,Verizon\n", encoding="utf-8"
    )
    ov = load_owner_overrides(csv)
    owner = pd.Series(["NEW PAR", "NEWPAR SMITH", "SMITH JOHN"])
    typ, n = apply_owner_overrides(owner, pd.Series(["Private"] * 3), ov)
    assert list(typ) == ["Corporate", "Private", "Private"] and n == 1
    csv.write_text("owner_name_pattern,owner_type,note\nX,Landlord,bad\n", encoding="utf-8")
    with pytest.raises(IngestError, match="dm_OwnerType"):
        load_owner_overrides(csv)


def test_market_owner_overrides_file_is_valid() -> None:
    ov = load_owner_overrides(REPO / "markets" / "franklin_oh" / "owner_overrides.csv")
    assert ov[0]["owner_type"] == "Corporate"


def test_largest_overlap_picks_bigger_share() -> None:
    parcels = _gdf([{"geometry": box(0, 0, 100, 100)}])
    zones = _gdf([
        {"zoning_code": "C4", "geometry": box(0, 0, 70, 100)},
        {"zoning_code": "R1", "geometry": box(70, 0, 200, 100)},
    ])  # fmt: skip
    assert largest_overlap(parcels, zones, "zoning_code").iloc[0] == "C4"


def test_assign_zoning_end_to_end() -> None:
    parcels = _gdf([
        {"parcel_id": "a", "jurisdiction": "Columbus", "geometry": box(0, 0, 100, 100)},
        {"parcel_id": "b", "jurisdiction": "Columbus", "geometry": box(1000, 0, 1100, 100)},
        {"parcel_id": "c", "jurisdiction": "Columbus", "geometry": box(1300, 0, 1400, 100)},
        {"parcel_id": "d", "jurisdiction": "DUBLIN CITY", "geometry": box(0, 500, 100, 600)},
        {"parcel_id": "e", "jurisdiction": "Columbus", "geometry": box(1600, 0, 1700, 100)},
    ])  # fmt: skip
    districts = _gdf([
        {"zoning_code": "C4", "jurisdiction": "Columbus", "geometry": box(-10, -10, 500, 700)},
        {"zoning_code": "DD", "jurisdiction": "Columbus", "geometry": box(900, -10, 1800, 200)},
    ])  # fmt: skip
    overlays = _gdf([
        {"overlay_code": "overlay:University/NC", "geometry": box(-10, -10, 60, 60)}
    ])  # fmt: skip
    parking = _gdf([
        {"zone": "A", "geometry": box(900, -10, 1200, 200)},
        {"zone": "B", "geometry": box(1200, -10, 1800, 200)},
    ])  # fmt: skip
    out, stats = assign_zoning(parcels, TABLE, districts, overlays, parking, 150.0)
    r = out.set_index("parcel_id")
    assert r.loc["a", "zoning_overlays"] == "overlay:University/NC"
    assert (r.loc["a", "zoning_screen"], r.loc["a", "zoning_status"]) == ("Unknown", "Review")
    # b: Zone A, 100 ft from B -> near the line -> Review, not Fail
    assert r.loc["b", "parking_zone"] == "A" and bool(r.loc["b", "parking_zone_near_boundary"])
    assert (
        r.loc["b", "zoning_status"] == "Review" and "near digitized" in r.loc["b", "zoning_reason"]
    )
    # c: Zone B, 100 ft from A -> Review; e: Zone B, 400 ft away -> Conditional Pass
    assert r.loc["c", "zoning_status"] == "Review"
    assert (r.loc["e", "parking_zone"], r.loc["e", "zoning_status"]) == ("B", "Pass")
    # d: another jurisdiction -> no Columbus code, Unknown -> Review
    assert r.loc["d", "zoning_code"] is None and r.loc["d", "zoning_status"] == "Review"
    assert stats["zoned"] == 4


def test_dd_without_parking_zones_reviews() -> None:
    parcels = _gdf([{"parcel_id": "x", "jurisdiction": "Columbus", "geometry": box(0, 0, 10, 10)}])
    districts = _gdf([{"zoning_code": "DD", "jurisdiction": "Columbus",
                       "geometry": box(-5, -5, 20, 20)}])  # fmt: skip
    out, _ = assign_zoning(parcels, TABLE, districts, None, None, 150.0)
    assert out.iloc[0]["zoning_status"] == "Review"


def test_rest_query_passes_generalization(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    class _R:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict[str, Any]:
            return {"features": []}

    def fake_get(url: str, params: dict[str, Any], timeout: int) -> _R:
        seen.update(params)
        return _R()

    monkeypatch.setattr(arcgis_rest.requests, "get", fake_get)
    arcgis_rest.query_to_geojson(
        "https://x/MapServer/28", (0, 0, 1, 1), tmp_path / "o.geojson",
        where="A=1", page_size=100, max_allowable_offset=1e-5, geometry_precision=6,
    )  # fmt: skip
    assert seen["where"] == "A=1" and seen["resultRecordCount"] == 100
    assert seen["maxAllowableOffset"] == "1e-05" and seen["geometryPrecision"] == 6


def test_licensed_stubs_not_configured(m1_run: Any) -> None:
    reg = m1_run.store.read_table("DataSourceRegistry").set_index("source_id")
    for sid in ("S01R", "S07", "S16", "S23", "S23b", "S23c"):
        assert reg.loc[sid, "status"] == "not configured", sid
        assert reg.loc[sid, "row_count"] == 0


def test_overlay_load_has_no_case_colliding_columns(tmp_path: Path) -> None:
    from parkiq.config import SourceEntry
    from parkiq.ingest.city_open_data import ZoningOverlaysAdapter

    com = _gdf([{"OVRLY_NAME": "X UCO", "TYPE": "URBAN COMMERCIAL OVERLAY", "ORD_NO": "1",
                 "geometry": box(0, 0, 10, 10)}]).to_crs(4326)  # fmt: skip
    plan = _gdf([{"OVERLAY_NAME": "University/NC", "geometry": box(20, 0, 30, 10)}]).to_crs(4326)
    a, b = tmp_path / "a.geojson", tmp_path / "b.geojson"
    com.to_file(a)
    plan.to_file(b)
    entry = SourceEntry(options={"type_codes": {"URBAN COMMERCIAL OVERLAY": "overlay:UCO"}})
    g = ZoningOverlaysAdapter(entry).load([a, b])
    lower = [c.lower() for c in g.columns]
    assert len(lower) == len(set(lower))
    assert sorted(g["overlay_code"]) == ["overlay:UCO", "overlay:University/NC"]


def test_onstreet_meters_shape() -> None:
    from shapely.geometry import LineString

    from parkiq.config import SourceEntry
    from parkiq.ingest.city_open_data import OnStreetMetersAdapter

    a = gpd.GeoDataFrame(
        {"segment_id": ["1", "2"], "res_type": ["Metered Parking", "Permit Parking"],
         "stalls_est": ["6", None], "rate_hour": ["1.00", None]},
        geometry=[LineString([(0, 0), (100, 0)]), LineString([(0, 10), (50, 10)])], crs=FT,
    )  # fmt: skip
    out = OnStreetMetersAdapter(SourceEntry()).shape(a, None)  # type: ignore[arg-type]
    assert list(out["metered_flag"]) == [True, False] and list(out["permit_flag"]) == [False, True]
    assert out["stalls_est"].iloc[0] == 6.0 and out["rate_hour"].iloc[0] == 1.0
