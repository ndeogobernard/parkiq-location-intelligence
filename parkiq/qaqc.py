"""QA/QC checks (SCOPE §10; tool 4 ``RunQAQC``). Results go to ``QAQC_Log``.

Check IDs follow the admin workbook's QA_Log (QA-01 … QA-13) where one exists; setup/grid
checks added here use QA-S* IDs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import pandas as pd
from pyproj import CRS

from parkiq.runner import RunContext, register
from parkiq.store import WGS84, utcnow

log = logging.getLogger(__name__)

# Layers produced by ingest that RunQAQC checks, with their ID field.
INGEST_LAYERS: dict[str, str | None] = {
    "Parcels": "parcel_id",
    "Buildings": "bldg_id",
    "Places": "place_id",
    "BlockJobs": "block_geoid",
    "BlockGroups": "bg_geoid",
    "TransitStops": "stop_id",
    "Venues": "venue_id",
    "Hospitals": "hospital_id",
    "Institutions": "unitid",
    "ParkingOSM": "osm_id",
    "TrafficCounts": None,
    "FloodHazard": None,
    "EnvSites": None,
}
AREA_TOL_REL = 1e-6  # numerical tolerance for tiling checks (fraction of area) — not a parameter


@dataclass
class Check:
    """One QA result."""

    check_id: str
    layer: str
    check_name: str
    result: str
    count: float | None
    threshold: str
    passed: bool
    severity: str = "error"  # error | warning | info


def write_checks(ctx: RunContext, step: str, checks: list[Check]) -> int:
    """Replace this step's QAQC_Log rows; return number of failed error-level checks."""
    rows = pd.DataFrame([{**c.__dict__, "step": step, "timestamp": utcnow()} for c in checks])
    ctx.store.write_table("QAQC_Log", rows, key={"step": step})
    failed = [c for c in checks if not c.passed and c.severity == "error"]
    for c in checks:
        lvl = (
            logging.INFO
            if c.passed
            else (logging.ERROR if c.severity == "error" else logging.WARNING)
        )
        log.log(lvl, "QA %s %s %s: %s", c.check_id, c.layer, c.check_name, c.result)
    return len(failed)


# --------------------------------------------------------------------------- generic checks


def layer_checks(
    gdf: gpd.GeoDataFrame, layer: str, id_field: str | None, want_crs: CRS, study: Any | None
) -> list[Check]:
    """CRS, extent, null/invalid geometry and duplicate-ID checks (SCOPE §10 Ingest)."""
    out: list[Check] = []
    crs_ok = gdf.crs is not None and CRS.from_user_input(gdf.crs).equals(want_crs)
    out.append(Check("QA-01", layer, "CRS = analysis_crs", str(gdf.crs), None, "100%", crs_ok))
    nulls = int((gdf.geometry.isna() | gdf.geometry.is_empty).sum())
    invalid = int((~gdf.geometry[gdf.geometry.notna()].is_valid).sum())
    out.append(Check("QA-02", layer, "null/empty geometry", str(nulls), nulls, "0", nulls == 0))
    out.append(Check("QA-02", layer, "invalid geometry", str(invalid), invalid, "0", invalid == 0))
    if study is not None and len(gdf):
        outside = int((~gdf.intersects(study)).sum())
        out.append(
            Check(
                "QA-01",
                layer,
                "features within StudyArea",
                f"{len(gdf) - outside}/{len(gdf)}",
                outside,
                "100%",
                outside == 0,
            )
        )
    if id_field and id_field in gdf.columns:
        dups = int(gdf[id_field].dropna().duplicated().sum())
        out.append(Check("QA-03", layer, f"duplicate {id_field}", str(dups), dups, "0", dups == 0))
    return out


def hex_tiling_checks(hexes: gpd.GeoDataFrame, study: Any) -> list[Check]:
    """HexGrid must not overlap or leave gaps (SCOPE §4.5 topology; manual §16)."""
    out: list[Check] = []
    total = float(hexes.geometry.area.sum())
    union = hexes.geometry.union_all()
    overlap = total - union.area
    ok = overlap <= AREA_TOL_REL * total
    out.append(
        Check(
            "QA-S01",
            "HexGrid",
            "no overlaps (Σarea − union area)",
            f"{overlap:.6g} units²",
            overlap,
            f"≤ {AREA_TOL_REL:g}×total",
            ok,
        )
    )
    holes = sum(len(p.interiors) for p in getattr(union, "geoms", [union]))
    out.append(
        Check(
            "QA-S02",
            "HexGrid",
            "no interior gaps (holes in union)",
            str(holes),
            holes,
            "0",
            holes == 0,
        )
    )
    parts = len(getattr(union, "geoms", [union]))
    out.append(
        Check(
            "QA-S03",
            "HexGrid",
            "contiguous (union parts)",
            str(parts),
            parts,
            "1",
            parts == 1,
            severity="warning",
        )
    )
    cover = union.intersection(study).area / study.area if study.area else 0.0
    out.append(
        Check(
            "QA-S04",
            "HexGrid",
            "share of StudyArea covered",
            f"{cover:.4f}",
            cover,
            "reported (centroid rule leaves edge slivers)",
            True,
            severity="info",
        )
    )
    return out


def check_setup(
    ctx: RunContext,
    boundary: gpd.GeoDataFrame,
    study: gpd.GeoDataFrame,
    hexes: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    edges: gpd.GeoDataFrame,
) -> int:
    """QA for SetupMarket outputs; returns failed error-level check count."""
    sa = study.union_all()
    checks: list[Check] = []
    checks += layer_checks(boundary, "MarketBoundary", None, ctx.cfg.crs, None)
    checks += layer_checks(hexes, "HexGrid", "hex_id", ctx.cfg.crs, sa)
    checks += hex_tiling_checks(hexes, sa)
    checks += layer_checks(edges, "WalkEdges", None, ctx.cfg.crs, None)
    neg = int((edges["walk_minutes"] <= 0).sum())
    checks.append(Check("QA-S05", "WalkEdges", "walk_minutes > 0", str(neg), neg, "0", neg == 0))
    import networkx as nx

    g = nx.Graph()
    g.add_edges_from(zip(edges["u"], edges["v"], strict=True))
    comps = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
    share = comps[0] / max(g.number_of_nodes(), 1) if comps else 0.0
    checks.append(
        Check(
            "QA-S06",
            "WalkEdges",
            "largest connected component share",
            f"{share:.4f} of {g.number_of_nodes()} nodes ({len(comps)} components)",
            share,
            "reported",
            True,
            severity="info",
        )
    )
    return write_checks(ctx, "setup", checks)


# --------------------------------------------------------------------------- step


@register("qaqc", deps=("ingest",), reads=())
def run_qaqc(ctx: RunContext) -> dict[str, Any]:
    """Tool 4 RunQAQC: ingest checks on every ingested layer present in the run."""
    study = ctx.store.read_layer("StudyArea").union_all()
    checks: list[Check] = []
    present = set(ctx.store.layers())
    for layer, idf in INGEST_LAYERS.items():
        if layer not in present:
            continue
        gdf = ctx.store.read_layer(layer)
        checks += layer_checks(gdf, layer, idf, ctx.cfg.crs, study)
    for layer in sorted(n for n in present if n.startswith("Raw_")):
        gdf = ctx.store.read_layer(layer, columns=["source_id"])
        ok = gdf.crs is not None and CRS.from_user_input(gdf.crs).equals(WGS84)
        checks.append(
            Check("QA-01", layer, "Raw snapshot CRS = EPSG:4326", str(gdf.crs), None, "100%", ok)
        )
    reg = ctx.store.read_table("DataSourceRegistry")
    nc = reg[reg["status"] == "not configured"]["source_id"].tolist() if len(reg) else []
    checks.append(
        Check(
            "QA-S07",
            "DataSourceRegistry",
            "sources not configured",
            ", ".join(nc) or "none",
            len(nc),
            "reported",
            True,
            severity="warning" if nc else "info",
        )
    )
    failed = write_checks(ctx, "qaqc", checks)
    if failed:
        raise RuntimeError(f"RunQAQC: {failed} error-level checks failed — see QAQC_Log")
    return {"checks": len(checks), "failed": failed, "not_configured": nc}
