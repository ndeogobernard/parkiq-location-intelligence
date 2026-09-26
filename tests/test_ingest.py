"""Adapter contract tests on the fixture (offline) and unit tests of adapter logic."""

from __future__ import annotations

import pandas as pd
import pytest

from parkiq.config import load_config
from parkiq.ingest.county_parcels import classify_owner, improvement_ratio
from parkiq.ingest.gtfs import active_services, to_minutes
from parkiq.runner import open_run, run_steps

# ------------------------------------------------------------------ unit


def test_owner_rules_first_match_wins() -> None:
    rules = [
        {"pattern": r"\bCITY\b", "owner_type": "Public"},
        {"pattern": r"\bLLC\b", "owner_type": "Corporate"},
    ]
    assert classify_owner("CITY PARKING LLC", rules) == "Public"
    assert classify_owner("acme llc", rules) == "Corporate"  # case-insensitive
    assert classify_owner("", rules) == "Unknown"
    assert classify_owner(None, rules) == "Unknown"
    assert classify_owner("JANE DOE", rules) == "Unknown"


def test_improvement_ratio_nullif() -> None:
    r = improvement_ratio(pd.Series([100, 0, None]), pd.Series([25, 10, 5]))
    assert r.iloc[0] == 0.25 and pd.isna(r.iloc[1]) and pd.isna(r.iloc[2])


def test_gtfs_time_and_calendar() -> None:
    assert to_minutes("25:15:00") == 25 * 60 + 15
    cal = pd.DataFrame(
        {
            "service_id": ["WK", "WE"],
            "monday": ["1", "0"],
            "tuesday": ["1", "0"],
            "wednesday": ["1", "0"],
            "thursday": ["1", "0"],
            "friday": ["1", "0"],
            "saturday": ["0", "1"],
            "sunday": ["0", "1"],
            "start_date": ["20260101"] * 2,
            "end_date": ["20271231"] * 2,
        }
    )
    dates = pd.DataFrame(
        {"service_id": ["WK", "X"], "date": ["20261126", "20261126"], "exception_type": ["2", "1"]}
    )
    assert active_services(cal, dates, "20261001") == {"WK"}  # Thursday
    assert active_services(cal, dates, "20261126") == {"X"}  # holiday swap
    assert active_services(cal, dates, "20261003") == {"WE"}  # Saturday


# ------------------------------------------------------------------ fixture contract


def test_every_adapter_loaded(m1_run) -> None:  # type: ignore[no-untyped-def]
    reg = m1_run.store.read_table("DataSourceRegistry").set_index("source_id")
    for sid in [
        "S00",
        "S01",
        "S02",
        "S03a",
        "S03b",
        "S04",
        "S05",
        "S06",
        "S08",
        "S09",
        "S10",
        "S12a",
        "S12b",
        "S13",
        "S14",
        "S15",
        "S18",
    ]:
        assert reg.loc[sid, "status"] == "loaded", sid
        if sid != "S00":
            assert "SYNTHETIC — NOT REAL DATA" in reg.loc[sid, "license"], sid


def test_clip_to_study_area(m1_run) -> None:  # type: ignore[no-untyped-def]
    s = m1_run.store
    assert len(s.read_layer("BlockJobs")) == 25  # 5 of 30 blocks lie outside
    assert len(s.read_layer("BlockGroups")) == 4  # 1 of 5 outside
    assert len(s.read_layer("Hospitals")) == 1  # 1 of 2 outside


def test_parcels_standardized(m1_run) -> None:  # type: ignore[no-untyped-def]
    p = m1_run.store.read_layer("Parcels")
    assert p["parcel_id"].is_unique  # multipart FX-0001 dissolved
    assert (p["lot_sqft"] > 0).all()
    assert set(p["land_use_class"]) <= {
        "Vacant",
        "SurfaceParking",
        "Commercial",
        "Residential",
        "Institutional",
        "Other",
    }
    assert (p.loc[p["land_use_code"] == "999", "land_use_class"] == "Other").all()
    pub = p[p["owner"] == "CITY OF FIXTURE"]
    assert (pub["owner_type"] == "Public").all()
    # lot_sqft is square feet even though the CRS is metres
    one = p.iloc[0]
    assert one["lot_sqft"] == pytest.approx(one.geometry.area * 10.7639104, rel=1e-6)


def test_transit_headways(m1_run) -> None:  # type: ignore[no-untyped-def]
    t = m1_run.store.read_layer("TransitStops").set_index("stop_id")
    assert list(t.index) == ["A", "B", "C"]  # parent station P excluded
    assert t.loc["A", "peak_departures"] == 12  # 07:00–08:50 every 10 min; weekend trip out
    assert t.loc["A", "peak_headway_min"] == 10
    assert t.loc["A", "high_frequency_flag"] == 1
    assert t.loc["B", "peak_headway_min"] == 30 and t.loc["B", "high_frequency_flag"] == 0
    assert pd.isna(t.loc["C", "peak_headway_min"])


def test_places_merge_two_sources(m1_run) -> None:  # type: ignore[no-untyped-def]
    pl = m1_run.store.read_layer("Places")
    assert set(pl["source_id"]) == {"S03a", "S03b"}
    assert pl["place_id"].is_unique
    assert not pl["category"].str.contains("school").any()  # not in the OSM tag query


def test_flood_and_env_flags(m1_run) -> None:  # type: ignore[no-untyped-def]
    f = m1_run.store.read_layer("FloodHazard")
    assert f["floodway_flag"].sum() == 1 and f["sfha_flag"].sum() == 2
    e = m1_run.store.read_layer("EnvSites").set_index("site_id")
    assert e.loc["E1", "brownfield_flag"] == 1 and e.loc["E2", "brownfield_flag"] == 0


def test_ipeds_enrollment_filter(m1_run) -> None:  # type: ignore[no-untyped-def]
    i = m1_run.store.read_layer("Institutions")
    assert i["enrollment"].tolist() == [12000]


def test_raw_snapshots_are_wgs84(m1_run) -> None:  # type: ignore[no-untyped-def]
    for name in m1_run.store.layers():
        if name.startswith("Raw_"):
            assert m1_run.store.read_layer(name).crs.to_epsg() == 4326, name


# ------------------------------------------------------------------ not-configured path


@pytest.mark.slow  # full fixture pipeline run; CI runs it (pytest -m 'not network and not arcpy')
def test_disabled_source_takes_not_configured_path(variant, fresh_out) -> None:  # type: ignore[no-untyped-def]
    cfg = load_config(variant({"sources.S12a.enabled": False}))
    ctx = open_run(cfg, run_id="20260101_0000_fixture_Balanced", out=fresh_out)
    run_steps(ctx, ["schema", "setup", "ingest"])
    reg = ctx.store.read_table("DataSourceRegistry").set_index("source_id")
    assert reg.loc["S12a", "status"] == "not configured"
    assert reg.loc["S12a", "row_count"] == 0
    # BuildSchema creates the layer empty; the disabled adapter writes nothing to it
    assert "Hospitals" not in ctx.store.written_layers()
    assert len(ctx.store.read_layer("Hospitals")) == 0
    log = ctx.log_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "S12a" in log and "not configured" in log and "effect:" in log


@pytest.mark.slow  # full fixture pipeline run; CI runs it (pytest -m 'not network and not arcpy')
def test_license_flag_gates_source(variant, fresh_out) -> None:  # type: ignore[no-untyped-def]
    cfg = load_config(variant({"sources.S02.license_flag": "regrid"}))  # regrid: false
    ctx = open_run(
        cfg, run_id="20260101_0000_fixture_Balanced", out=fresh_out, source_filter=["S02"]
    )
    run_steps(ctx, ["schema", "setup", "ingest"])
    reg = ctx.store.read_table("DataSourceRegistry").set_index("source_id")
    assert reg.loc["S02", "status"] == "not configured"
    assert "data_licenses.regrid" in reg.loc["S02", "notes"]


def test_secrets_are_redacted() -> None:
    from parkiq.ingest.base import redact

    msg = "404 for url: https://api.census.gov/data/2023/acs/acs5?get=NAME&key=abc123SECRET&x=1"
    out = redact(msg)
    assert "abc123SECRET" not in out and "key=***" in out and "x=1" in out
    assert redact("https://h/x?token=t0k") == "https://h/x?token=***"


def test_params_yaml_never_contains_key(m1_run, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    text = (m1_run.run_dir / "params.yaml").read_text(encoding="utf-8")
    assert "api_key_env: CENSUS_API_KEY" in text  # only the variable *name* is recorded
    import os

    key = os.environ.get("CENSUS_API_KEY")
    if key:
        assert key not in text
