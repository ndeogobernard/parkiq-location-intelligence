"""BuildSchema, schema-diff, domain constraints and generated docs (M2)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import geopandas as gpd
import pytest
from pyproj import CRS
from shapely.geometry import Point

from parkiq.schema import Schema, SchemaError
from parkiq.schema_build import (
    build_schema,
    data_dictionary,
    erd_drawio,
    schema_diff,
    subtypes_frame,
)
from parkiq.store import Store

REPO = Path(__file__).parents[1]
SCHEMA = Schema.load(REPO / "schema" / "schema.yaml")
CRS_A = CRS.from_epsg(3735)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    p = tmp_path_factory.mktemp("schema") / "built.gpkg"
    build_schema(p, SCHEMA, CRS_A)
    return p


def test_build_then_diff_is_empty(built: Path) -> None:
    assert schema_diff(built, SCHEMA, CRS_A) == []


def test_every_scope_class_present() -> None:
    scope = {
        "MarketBoundary", "Submarkets", "HexGrid", "WalkNodes", "WalkEdges", "Parcels",
        "Buildings", "DemandAnchors", "TransitStops", "Venues", "SupplyFacilities",
        "OnStreetSegments", "HotZones", "CandidateParcels", "WalkSheds", "SiteScores",
        "SiteFinancials", "Shortlist", "DataSourceRegistry", "ParkingRates",
        "CriteriaDefinitions", "WeightScenarios", "FinanceParams", "ScoreRuns", "QAQC_Log",
        "Validation", "Hex_Demand_Daypart", "Hex_Supply_Daypart", "Hex_Gap_Daypart",
    }  # fmt: skip
    assert scope <= set(SCHEMA.layers)


def test_diff_detects_changes(built: Path, tmp_path: Path) -> None:
    p = tmp_path / "changed.gpkg"
    p.write_bytes(built.read_bytes())
    with sqlite3.connect(p) as con:
        con.execute('ALTER TABLE "Parcels" ADD COLUMN surprise TEXT')
        con.execute('DROP TABLE "Shortlist"')
        con.execute("DELETE FROM gpkg_data_column_constraints WHERE value = 'Review'")
    diffs = schema_diff(p, SCHEMA, CRS_A)
    assert any("Parcels: extra columns ['surprise']" in d for d in diffs)
    assert any(d.startswith("Shortlist: missing") for d in diffs)
    assert any("dm_ScreenStatus" in d for d in diffs)


def test_domains_are_gpkg_constraints(built: Path) -> None:
    with sqlite3.connect(built) as con:
        vals = {
            r[0]
            for r in con.execute(
                "SELECT value FROM gpkg_data_column_constraints"
                " WHERE constraint_name = 'dm_LandUseClass'"
            )
        }
        attached = con.execute(
            "SELECT constraint_name FROM gpkg_data_columns"
            " WHERE table_name = 'Parcels' AND column_name = 'land_use_class'"
        ).fetchone()[0]
        rng = con.execute(
            "SELECT min, max FROM gpkg_data_column_constraints WHERE constraint_name = 'rg_Score'"
        ).fetchone()
    assert "SurfaceParking" in vals and attached == "dm_LandUseClass" and tuple(rng) == (0, 100)


def test_domain_violation_rejected_on_write(built: Path, tmp_path: Path) -> None:
    p = tmp_path / "w.gpkg"
    p.write_bytes(built.read_bytes())
    store = Store(p, SCHEMA, "r1", CRS_A)
    bad = gpd.GeoDataFrame(
        {"zone": ["C"], "jurisdiction": ["Columbus"]}, geometry=[Point(0, 0).buffer(10)], crs=CRS_A
    )
    with pytest.raises(SchemaError, match="dm_ParkingZone"):
        store.write_layer("ParkingZones", bad, "S23c")
    good = bad.assign(zone="A")
    assert store.write_layer("ParkingZones", good, "S23c") == 1
    assert schema_diff(p, SCHEMA, CRS_A) == []  # constraints re-attached after the rewrite


def test_subtypes_and_relationships() -> None:
    sub = subtypes_frame(SCHEMA)
    assert set(sub["layer"]) == {"Parcels", "SupplyFacilities"}
    assert len(SCHEMA.relationships) >= 7
    xml = erd_drawio(SCHEMA)
    assert 'source="CandidateParcels" target="SiteScores"' in xml


def test_generated_docs_are_current() -> None:
    doc = (REPO / "docs" / "DataDictionary.md").read_text(encoding="utf-8")
    assert doc == data_dictionary(SCHEMA), "run `parkiq schema-docs` to regenerate docs"
    drawio = (REPO / "docs" / "ERD.drawio").read_text(encoding="utf-8")
    assert drawio == erd_drawio(SCHEMA), "run `parkiq schema-docs` to regenerate docs"
