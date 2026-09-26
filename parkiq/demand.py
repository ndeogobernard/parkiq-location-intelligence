"""Step ``demand``, Phase B demand model (SCOPE §5.2; ADR-0013, 0014, 0022, 0068–0070).

Anchors (``DemandAnchors``) and their size metric, per ``configs/anchor_crosswalk.yaml``:

* **Office**: LODES WAC jobs in office-type sectors only (CNS09–14, CNS20); other sectors carry no
  per-job rate and generate no job-based demand.
* **Medical**: hospital beds (S12a). **University**: enrollment (S12b).
* **Hotel**: OSM ``rooms``, else building floor area ÷ ``demand.hotel_sqft_per_room``.
* **RestaurantBar / Retail**: ground-floor footprint of the containing building, shared among the
  places in it (no building → skipped and counted).
* **Venue**: S10 seats × events (blank = unknown → skipped with a WARNING, never 0).

Demand per daypart = size × rate × calibration × mode factor × transit factor, where
* the **mode factor** (commute categories only) = workplace drive share of the place the anchor is
  in ÷ county workplace drive share (ACS B08601, work-from-home excluded) (ADR-0068);
* the **transit factor** applies to non-commute categories within the high-frequency radius of a
  high-frequency stop, commute shares already reflect transit use (ADR-0068);
* **campus rule** (ADR-0070): jobs of the named sectors on an anchor's campus (parcel under the
  anchor + contiguous parcels with the same normalized owner) are removed from job-based demand.

Anchors are allocated to hexes with the walk-shed decay (demand-conserving) → ``Hex_Demand_Daypart``
with ``components_json`` by category. Per-anchor allocation weights are kept for the gap step
(single-anchor hot zones).
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from parkiq import units
from parkiq.allocation import WalkGraph, allocate_matrix
from parkiq.config import DAYPARTS
from parkiq.qaqc import Check, write_checks
from parkiq.runner import register

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)
SQFT_PER_SQM = 10.7639


def norm_owner(v: Any) -> str:
    """Owner name normalized for campus matching (case, punctuation, spacing)."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]+", " ", str(v or "").upper())).strip()


def campus_parcels(parcels: gpd.GeoDataFrame, point: Any, search_ft: float = 8000.0) -> Any:
    """Union of the parcel under ``point`` and contiguous parcels with the same owner."""
    near = parcels[parcels.intersects(point.buffer(search_ft))]
    seed = near[near.contains(point)]
    if seed.empty:
        return None
    owner = norm_owner(seed["owner"].iloc[0])
    if not owner:
        return seed.geometry.iloc[0]
    same = near[near["owner"].map(norm_owner) == owner]
    geoms = list(same.geometry)
    grown = seed.geometry.iloc[0]
    changed = True
    while changed:  # grow by adjacency (touching within 1 ft)
        changed = False
        rest = []
        for g in geoms:
            if g.distance(grown) <= 1.0 and not g.equals(grown):
                grown = grown.union(g)
                changed = True
            else:
                rest.append(g)
        geoms = rest
    return grown


def _tags(v: Any) -> dict[str, Any]:
    try:
        return dict(json.loads(v)) if isinstance(v, str) and v else {}
    except ValueError:
        return {}


def place_category(cat: str, rules: list[dict[str, Any]]) -> str | None:
    """Anchor category of an OSM/Overture place category string ``key=value``."""
    if "=" not in str(cat):
        return None
    k, v = str(cat).split("=", 1)
    for r in rules:
        vals = r["match"].get(k)
        if vals == "*" or (isinstance(vals, list) and v in vals):
            return str(r["category"])
    return None


def building_share(
    pts: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(footprint sq ft share, levels, height m) of the building containing each point."""
    j = gpd.sjoin(
        pts[["geometry"]],
        buildings[["area_sqft", "levels", "height_m", "geometry"]],
        predicate="within",
    )
    j = j[~j.index.duplicated()]
    n = j.groupby("index_right").size()
    share = j["area_sqft"] / j["index_right"].map(n)
    return (
        share.reindex(pts.index),
        j["levels"].reindex(pts.index),
        j["height_m"].reindex(pts.index),
    )


def build_anchors(ctx: RunContext, xw: dict[str, Any]) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """All demand anchors with size metrics (before rates)."""
    cfg, dm = ctx.cfg, ctx.cfg.market.demand
    crs = cfg.crs
    written = set(ctx.store.written_layers())
    excluded = set(dm.excluded_anchor_categories)
    rows: list[gpd.GeoDataFrame] = []
    rep: dict[str, Any] = {"skipped": {}}

    parcels = ctx.store.read_layer("Parcels", columns=["owner"])

    # ---- campuses (Medical / University) and on-campus jobs to remove (ADR-0070)
    jobs = ctx.store.read_layer("BlockJobs")
    sectors = jobs["sectors_json"].map(_tags)
    remove = {k: pd.Series(0.0, index=jobs.index) for k in ("CNS15", "CNS16")}
    campus_report: dict[str, Any] = {}

    def campus_for(layer: gpd.GeoDataFrame, cat: str) -> None:
        secs = dm.campus_rule.get(cat, [])
        if not secs:
            return
        removed = 0.0
        for g in layer.geometry:
            c = campus_parcels(parcels, g)
            if c is None:
                continue
            on = jobs.geometry.within(c)
            if not on.any():
                continue
            for s in secs:
                vals = sectors[on].map(lambda d, s=s: float(d.get(s, 0) or 0)).astype(float)
                remove.setdefault(s, pd.Series(0.0, index=jobs.index))
                remove[s].loc[vals.index] = vals.to_numpy()
                removed += float(vals.sum())
        campus_report[cat] = {"sectors": secs, "jobs_on_campus_removed": removed}

    # ---- Office from LODES
    office_secs = list(xw["lodes_sectors"]["Office"])
    if "Office" not in excluded:
        office = sectors.map(lambda d: sum(float(d.get(s, 0) or 0) for s in office_secs))
        for s in office_secs:
            if s in remove:
                office = office - remove[s]
        g = gpd.GeoDataFrame(
            {
                "category": "Office",
                "name": None,
                "size_metric": "Jobs",
                "size_value": office.clip(lower=0),
                "origin": "S04:" + jobs["block_geoid"].astype(str),
            },
            geometry=jobs.geometry,
            crs=crs,
        )
        rows.append(g[g["size_value"] > 0])
    by_sector = {
        s: float(sectors.map(lambda d, s=s: float(d.get(s, 0) or 0)).sum())
        for s in [f"CNS{i:02d}" for i in range(1, 21)]
    }
    rep["lodes_jobs_by_sector"] = by_sector

    # ---- Medical
    if "Medical" not in excluded and "Hospitals" in written:
        h = ctx.store.read_layer("Hospitals")
        campus_for(h, "Medical")
        h = h[h["beds"].notna() & (h["beds"] > 0)]
        rows.append(
            gpd.GeoDataFrame(
                {
                    "category": "Medical",
                    "name": h["name"],
                    "size_metric": "Beds",
                    "size_value": h["beds"],
                    "origin": "S12a:" + h["hospital_id"],
                },
                geometry=h.geometry,
                crs=crs,
            )
        )
    # ---- University
    if "University" not in excluded and "Institutions" in written:
        u = ctx.store.read_layer("Institutions")
        campus_for(u, "University")
        u = u[u["enrollment"].notna() & (u["enrollment"] > 0)]
        rows.append(
            gpd.GeoDataFrame(
                {
                    "category": "University",
                    "name": u["name"],
                    "size_metric": "Enrollment",
                    "size_value": u["enrollment"],
                    "origin": "S12b:" + u["unitid"].astype(str),
                },
                geometry=u.geometry,
                crs=crs,
            )
        )
    rep["campus_rule"] = campus_report

    # ---- Places: hotels, restaurants/bars, retail
    places = ctx.store.read_layer("Places")
    places["acat"] = places["category"].map(lambda c: place_category(c, xw["places"]))
    places = places[places["acat"].notna() & ~places["acat"].isin(excluded)].copy()
    bld = ctx.store.read_layer("Buildings", columns=["area_sqft", "levels", "height_m"])
    share, levels, height = building_share(places, bld)
    rooms = places["tags_json"].map(lambda t: _tags(t).get("rooms"))
    rooms = pd.to_numeric(rooms.astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    floors = levels.fillna(np.round(height / float(dm.meters_per_floor or 1))).clip(lower=1)
    est_rooms = (share * floors / float(dm.hotel_sqft_per_room or np.inf)).round(0)
    hotel = places["acat"] == "Hotel"
    size = pd.Series(np.nan, index=places.index)
    size[hotel] = rooms[hotel].fillna(est_rooms[hotel])
    area_cats = places["acat"].isin(["RestaurantBar", "Retail"])
    cap = places["acat"].map(lambda c: float(dm.floor_area_cap_sqft.get(c, np.inf)))
    size[area_cats] = np.minimum(share[area_cats], cap[area_cats]) / 1000.0  # sqft_k, ground floor
    capped = area_cats & (share > cap)
    metric = places["acat"].map({"Hotel": "Rooms", "RestaurantBar": "Sqft", "Retail": "Sqft"})
    rep["places"] = {
        "hotels": int(hotel.sum()),
        "hotel_rooms_tagged": int(rooms[hotel].notna().sum()),
        "hotel_rooms_estimated": int((rooms[hotel].isna() & est_rooms[hotel].notna()).sum()),
        "floor_area_capped": {
            c: int((capped & places["acat"].eq(c)).sum()) for c in ("RestaurantBar", "Retail")
        },
        "no_building": {
            c: int((places["acat"].eq(c) & size.isna()).sum())
            for c in ("Hotel", "RestaurantBar", "Retail")
        },
    }
    ok = size.notna() & (size > 0)
    rows.append(
        gpd.GeoDataFrame(
            {
                "category": places.loc[ok, "acat"],
                "name": places.loc[ok, "name"],
                "size_metric": metric[ok],
                "size_value": size[ok],
                "origin": places.loc[ok, "place_id"],
            },
            geometry=places.loc[ok].geometry,
            crs=crs,
        )
    )

    # ---- Venues (S10): blank = unknown → skipped with a warning (Bernard, M3 decisions)
    if "Venue" not in excluded and "Venues" in written:
        v = ctx.store.read_layer("Venues")
        unk = v["seats"].isna() | v["events_per_year"].isna()
        for n in v.loc[unk, "name"]:
            log.warning("venue %s: seats or events unknown, event demand skipped", n)
        rep["skipped"]["venues_unknown"] = list(v.loc[unk, "name"])
        v = v[~unk]
        rows.append(
            gpd.GeoDataFrame(
                {
                    "category": "Venue",
                    "name": v["name"],
                    "size_metric": "Seats",
                    "size_value": v["seats"],
                    "origin": "S10:" + v["venue_id"],
                    "venue_id": v["venue_id"],
                },
                geometry=v.geometry,
                crs=crs,
            )
        )
    elif "Venues" not in written:
        rep["skipped"]["venues"] = "S10 not configured, no event demand"
    a = gpd.GeoDataFrame(pd.concat(rows, ignore_index=True), crs=crs)
    return a, rep


def mode_factors(a: gpd.GeoDataFrame, ctx: RunContext) -> pd.Series:
    """Workplace drive share of the anchor's place ÷ county share (commute categories only)."""
    dm = ctx.cfg.market.demand
    f = pd.Series(1.0, index=a.index)
    if dm.mode_adjustment != "relative" or dm.workplace_drive_share_path is None:
        return f
    t = pd.read_csv(dm.workplace_drive_share_path, dtype={"geoid": str})
    base = float(t.loc[t["geography"] == "county", "drive_share"].iloc[0])
    if dm.workplace_min_commuters is not None and "commuters" in t.columns:
        small = t["commuters"] < dm.workplace_min_commuters
        t.loc[small & (t["geography"] != "county"), "drive_share"] = np.nan  # → county (factor 1)
    if dm.workplace_places_path is None:
        return f
    pl = gpd.read_file(dm.workplace_places_path).to_crs(a.crs)
    share = dict(zip(t["geoid"], t["drive_share"], strict=True))
    pl["share"] = pl["GEOID"].map(share)
    commute = a["category"].isin(dm.commute_categories)
    j = gpd.sjoin(a.loc[commute, ["geometry"]], pl[["share", "geometry"]], predicate="within")
    j = j[~j.index.duplicated()]
    f.loc[j.index] = (j["share"] / base).fillna(1.0)
    return f


def transit_factors(a: gpd.GeoDataFrame, ctx: RunContext) -> pd.Series:
    """demand_factor within the radius of a high-frequency stop, non-commute categories only."""
    ta = ctx.cfg.market.demand.transit_adjustment
    f = pd.Series(1.0, index=a.index)
    if "TransitStops" not in set(ctx.store.written_layers()):
        return f
    s = ctx.store.read_layer("TransitStops")
    hf = s[s["high_frequency_flag"].fillna(0).astype(bool)]
    if hf.empty:
        return f
    r = units.m_to_crs(ta.high_frequency_radius_m, a.crs)
    zone = hf.geometry.buffer(r).union_all()
    non = ~a["category"].isin(ctx.cfg.market.demand.commute_categories)
    near = a.geometry.within(zone) & non
    f[near] = ta.demand_factor
    return f


@register(
    "demand",
    deps=("qaqc",),
    reads=("market.demand", "rates", "market.network", "market.site"),
    milestone="M4",
)
def run_demand(ctx: RunContext) -> dict[str, Any]:
    """Phase B: anchors, generation, allocation to hexes."""
    cfg, dm = ctx.cfg, ctx.cfg.market.demand
    xw = yaml.safe_load((cfg.config_dir / "anchor_crosswalk.yaml").read_text(encoding="utf-8"))
    a, rep = build_anchors(ctx, xw)
    if dm.workplace_source_id and dm.workplace_source_id in cfg.sources:
        from parkiq.ingest.base import register_source

        register_source(
            ctx,
            dm.workplace_source_id,
            cfg.sources[dm.workplace_source_id],
            status="loaded",
            row_count=len(pd.read_csv(dm.workplace_drive_share_path))
            if dm.workplace_drive_share_path
            else 0,
            endpoint=f"local: {dm.workplace_drive_share_path}",
            notes="workplace drive share for the office mode factor (ADR-0073)",
        )
    rates = {r.anchor_category: r for r in cfg.rates.rates.values()}
    calib = cfg.rates.calibration_factors
    a["mode_factor"] = mode_factors(a, ctx)
    a["transit_factor"] = transit_factors(a, ctx)
    mat = np.zeros((len(a), len(DAYPARTS)))
    for k, dp in enumerate(DAYPARTS):
        rate = a["category"].map(lambda c, dp=dp: getattr(rates[c], dp) if c in rates else 0.0)
        cf = a["category"].map(
            lambda c, dp=dp: (
                float((calib.get(c) or {}).get(dp, 1.0)) if isinstance(calib.get(c), dict) else 1.0
            )
        )
        att = a["category"].map(
            lambda c, dp=dp: float(dm.attendance_factor.get(c, {}).get(dp, 1.0))
        )
        mat[:, k] = a["size_value"] * rate * cf * att * a["mode_factor"] * a["transit_factor"]
        a[f"demand_{dp}"] = mat[:, k]
    a["anchor_id"] = [f"A{i:06d}" for i in range(1, len(a) + 1)]
    for c in ("drive_share", "venue_id"):
        if c not in a.columns:
            a[c] = None
    ctx.store.write_layer(
        "DemandAnchors",
        a[
            [
                "anchor_id",
                "category",
                "name",
                "size_metric",
                "size_value",
                "drive_share",
                "venue_id",
                "origin",
                "mode_factor",
                "transit_factor",
                *[f"demand_{d}" for d in DAYPARTS],
                "geometry",
            ]
        ],
        "DERIVED",
    )

    hexes = ctx.store.read_layer("HexGrid")
    graph = WalkGraph.from_layers(
        ctx.store.read_layer("WalkNodes"),
        ctx.store.read_layer("WalkEdges"),
        cfg.crs,
        cfg.market.network.walking_speed_m_s,
    )
    bands = [float(b) for b in dm.walk_shed_minutes]
    wts = {float(k): float(v) for k, v in dm.decay_weights.items()}
    out, stats, w = allocate_matrix(a, mat, hexes, graph, bands, wts, keep_weights=True)
    assert w is not None
    w["anchor_id"] = a["anchor_id"].to_numpy()[w["src"].to_numpy()]
    w["category"] = a["category"].to_numpy()[w["src"].to_numpy()]
    w.drop(columns="src").to_parquet(ctx.run_dir / "demand_weights.parquet", index=False)
    # components by category and daypart
    comp = {}
    for k, dp in enumerate(DAYPARTS):
        v = w.assign(d=w["w"] * mat[w["src"].to_numpy(), k])
        comp[dp] = v.groupby(["hex_id", "category"])["d"].sum().unstack(fill_value=0.0)
    rows = []
    for k, dp in enumerate(DAYPARTS):
        cdf = comp[dp].reindex(out.index).fillna(0.0).round(2)
        cj = [json.dumps({c: v for c, v in r.items() if v > 0}) for r in cdf.to_dict("records")]
        rows.append(
            pd.DataFrame(
                {
                    "hex_id": out.index,
                    "daypart": dp,
                    "demand_stalls": out[k].values,
                    "components_json": cj,
                    "method": "rates × size × mode × transit; walk-shed decay (M4)",
                }
            )
        )
    ctx.store.write_table("Hex_Demand_Daypart", pd.concat(rows, ignore_index=True))

    tot_a = mat.sum(axis=0)
    tot_h = out.sum(axis=0).to_numpy()
    cons = float(tot_h.sum() / tot_a.sum()) if tot_a.sum() else 1.0
    write_checks(
        ctx,
        "demand",
        [
            Check(
                "QA-D01",
                "Hex_Demand_Daypart",
                "allocation conserves demand (Σhex ÷ Σanchor)",
                f"{tot_h.sum():,.0f} of {tot_a.sum():,.0f}",
                cons,
                ">= 99%",
                cons >= 0.99,
                severity="warning",
            ),
        ],
    )
    rep.update(
        {
            "anchors_by_category": a.groupby("category").size().to_dict(),
            "size_by_category": a.groupby("category")["size_value"].sum().round(0).to_dict(),
            "demand_by_category": {
                c: {dp: float(g[f"demand_{dp}"].sum()) for dp in DAYPARTS}
                for c, g in a.groupby("category")
            },
            "demand_total": dict(zip(DAYPARTS, map(float, tot_a), strict=True)),
            "allocated_total": dict(zip(DAYPARTS, map(float, tot_h), strict=True)),
            "conservation": cons,
            "allocation": stats,
            "mode_factor": a.loc[a["category"].isin(dm.commute_categories), "mode_factor"]
            .describe()
            .round(4)
            .to_dict(),
            "transit_factor_applied": int((a["transit_factor"] < 1).sum()),
            "attendance_factor": dm.attendance_factor,
        }
    )
    (ctx.run_dir / "demand_report.json").write_text(
        json.dumps(rep, indent=1, default=str), encoding="utf-8"
    )
    return {"anchors": len(a), "wd_day": float(tot_a[0]), "conservation": cons}
