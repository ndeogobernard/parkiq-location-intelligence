"""Runner (resume, idempotency, gating, artifacts) and store (schema enforcement)."""

from __future__ import annotations

import json
from datetime import datetime

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from shapely.geometry import Point

from parkiq.config import load_config
from parkiq.runner import (
    StepBlocked,
    StepNotImplemented,
    new_run_id,
    open_run,
    read_run_log,
    resolve_steps,
    run_steps,
)
from parkiq.schema import SchemaError
from tests.conftest import FIXTURE_YAML


def test_run_id_format() -> None:
    assert (
        new_run_id("franklin_oh", "Balanced", datetime(2026, 10, 1, 9, 0))
        == "20261001_0900_franklin_oh_Balanced"
    )


def test_resolve_steps_orders_and_validates() -> None:
    assert resolve_steps("ingest,schema") == ["schema", "ingest"]
    with pytest.raises(ValueError):
        resolve_steps("schema,nope")


def test_run_artifacts(m1_run) -> None:  # type: ignore[no-untyped-def]
    d = m1_run.run_dir
    params = yaml.safe_load((d / "params.yaml").read_text(encoding="utf-8"))
    assert params["run_id"] == m1_run.run_id and "finance" in params and "sources" in params
    log = json.loads((d / "run_log.json").read_text(encoding="utf-8"))
    status = {k: v["status"] for k, v in log["steps"].items()}
    # slow M3/M4 tests may add later steps to this shared run; the M1 steps must have succeeded
    assert all(status[s] == "succeeded" for s in ("schema", "setup", "ingest", "qaqc"))
    ds = pd.read_csv(d / "data_sources.csv")
    assert {"source_id", "vintage", "license", "native_crs", "transformation"} <= set(ds.columns)
    assert (d / "rasters" / "Slope_pct.tif").exists()
    assert (d / "logs" / f"{m1_run.run_id}.log").exists()
    runs = m1_run.store.read_table("ScoreRuns")
    assert {"schema", "setup", "ingest", "qaqc"} <= set(runs["step"])


def test_every_layer_has_lineage(m1_run) -> None:  # type: ignore[no-untyped-def]
    reg = m1_run.store.read_table("_ParkIQ_Layers")
    for name in reg.loc[reg["kind"] == "features", "layer"]:
        g = m1_run.store.read_layer(name)
        assert {"source_id", "run_id", "load_ts"} <= set(g.columns), name
        assert (g["run_id"] == m1_run.run_id).all(), name


def test_qa_all_error_checks_pass(m1_run) -> None:  # type: ignore[no-untyped-def]
    qa = m1_run.store.read_table("QAQC_Log")
    bad = qa[(qa["severity"] == "error") & (qa["passed"] == 0)]
    assert bad.empty, bad.to_string()
    assert {"QA-01", "QA-02", "QA-03", "QA-S01", "QA-S02"} <= set(qa["check_id"])


def test_walk_minutes_in_edges(m1_run) -> None:  # type: ignore[no-untyped-def]
    e = m1_run.store.read_layer("WalkEdges")
    assert e["length_m"].round(6).eq(125.0).all()
    assert e["walk_minutes"].iloc[0] == pytest.approx(125 / 1.3 / 60)


@pytest.mark.slow  # full fixture pipeline run; CI runs it (pytest -m 'not network and not arcpy')
def test_resume_skips_and_force_reruns(fixture_cfg, fresh_out) -> None:  # type: ignore[no-untyped-def]
    ctx = open_run(fixture_cfg, run_id="20260101_0000_fixture_Balanced", out=fresh_out)
    run_steps(ctx, ["schema", "setup"])
    n1 = len(ctx.store.read_layer("HexGrid"))
    ctx2 = open_run(fixture_cfg, run_id=ctx.run_id, out=fresh_out)
    r = run_steps(ctx2, ["schema", "setup"])
    assert r["setup"].get("skipped") is True
    ctx3 = open_run(fixture_cfg, run_id=ctx.run_id, out=fresh_out, force=True)
    r = run_steps(ctx3, ["setup"])
    assert not r["setup"].get("skipped")
    assert len(ctx3.store.read_layer("HexGrid")) == n1  # idempotent, no duplicates
    reg = ctx3.store.read_table("DataSourceRegistry")
    assert reg["source_id"].value_counts().max() == 1  # one row per source per run


@pytest.mark.slow  # full fixture pipeline run; CI runs it (pytest -m 'not network and not arcpy')
def test_ingest_twice_is_idempotent(fixture_cfg, fresh_out) -> None:  # type: ignore[no-untyped-def]
    ctx = open_run(fixture_cfg, run_id="20260101_0000_fixture_Balanced", out=fresh_out)
    run_steps(ctx, ["schema", "setup", "ingest"])
    counts = {n: len(ctx.store.read_layer(n)) for n in ("Parcels", "Places", "BlockJobs")}
    ctx2 = open_run(fixture_cfg, run_id=ctx.run_id, out=fresh_out, source_filter=["S03b"])
    run_steps(ctx2, ["ingest"])
    # partial re-ingest keeps the other source's rows in the shared Places layer
    assert {n: len(ctx2.store.read_layer(n)) for n in counts} == counts
    assert set(ctx2.store.read_layer("Places")["source_id"]) == {"S03a", "S03b"}


def test_dependency_blocking_and_unimplemented(fixture_cfg, fresh_out) -> None:  # type: ignore[no-untyped-def]
    ctx = open_run(fixture_cfg, run_id="20260101_0000_fixture_Balanced", out=fresh_out)
    with pytest.raises(StepBlocked, match="needs 'setup'"):
        run_steps(ctx, ["ingest"])
    with pytest.raises(StepNotImplemented):
        run_steps(ctx, ["schema", "screen"], stop_at_unimplemented=False)


def test_decide_value_blocks_step(variant, fresh_out, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import parkiq.config as pc

    monkeypatch.setitem(pc.STEP_REQUIREMENTS, "setup", ["finance.capture_share"])
    cfg = load_config(variant({"finance.capture_share": None}))
    ctx = open_run(cfg, run_id="20260101_0000_fixture_Balanced", out=fresh_out)
    run_steps(ctx, ["schema"])
    with pytest.raises(StepBlocked, match=r"finance.capture_share"):
        run_steps(ctx, ["setup"])


@pytest.mark.slow  # full fixture pipeline run; CI runs it (pytest -m 'not network and not arcpy')
def test_stale_marking_after_upstream_rerun(fixture_cfg, fresh_out) -> None:  # type: ignore[no-untyped-def]
    ctx = open_run(fixture_cfg, run_id="20260101_0000_fixture_Balanced", out=fresh_out)
    run_steps(ctx, ["schema", "setup", "ingest"])
    ctx2 = open_run(fixture_cfg, run_id=ctx.run_id, out=fresh_out, force=True)
    run_steps(ctx2, ["setup"])
    assert read_run_log(ctx2)["steps"]["ingest"]["status"] == "stale"
    with pytest.raises(StepBlocked):
        run_steps(open_run(fixture_cfg, run_id=ctx.run_id, out=fresh_out), ["qaqc"])


def test_store_rejects_domain_violation_and_wrong_crs(m1_run) -> None:  # type: ignore[no-untyped-def]
    g = gpd.GeoDataFrame(
        {"venue_id": ["x"], "name": ["n"]}, geometry=[Point(0, 0)], crs="EPSG:4326"
    )
    with pytest.raises(SchemaError, match="CRS"):
        m1_run.store.write_layer("Venues", g, "TEST")
    p = m1_run.store.read_layer("Parcels").head(1).drop(columns=["run_id", "load_ts", "source_id"])
    p["land_use_class"] = "Parking"  # not in dm_LandUseClass
    with pytest.raises(SchemaError, match="dm_LandUseClass"):
        m1_run.store.write_layer("Parcels", p, "TEST")
    p["land_use_class"] = "Vacant"
    p["surprise"] = 1
    with pytest.raises(SchemaError, match="columns not in schema"):
        m1_run.store.write_layer("Parcels", p, "TEST")


def test_fixture_yaml_untouched() -> None:
    assert "SYNTHETIC" in FIXTURE_YAML.read_text(encoding="utf-8")
