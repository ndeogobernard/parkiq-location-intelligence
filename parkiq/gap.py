"""Step ``gap``, Phase D gap analysis and hot zones (SCOPE §5.4; ADR-0024, 0071, 0075).

``gap_stalls = demand − effective supply`` and ``gap_ratio = demand / supply`` per hex and daypart
(``rate_index`` stays null until the rate surface exists, ADR-0023). A hex qualifies for a hot zone
when its weekday-day gap is positive and its gap is also positive in at least one evening or event
daypart (wd_eve, we_eve, event). Qualifying hexes that share an edge (H3 k = 1) form one zone.

Paid-market mask (ADR-0075): a hex is *paid market* when paid parking exists within the largest
walk band (metered curb, ``fee=yes`` facilities, paid-operator facilities, survey observations with
a posted price). Zones built from qualifying paid-market hexes are **screening** zones (they feed
M5); zones from the remaining qualifying hexes are kept as "free-parking area, context only".

Flags per zone (ADR-0071): ``zone_size`` / ``single_hex_flag``; ``single_anchor_flag`` when one
anchor contributes more than ``demand.single_anchor_share`` of the zone's positive weekday-day gap;
``curb_sensitive_*`` from the supply step; ``below_min_lot_flag``; ``jurisdictions`` touched.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

from parkiq.allocation import WalkGraph, allocate_matrix
from parkiq.config import DAYPARTS
from parkiq.qaqc import Check, write_checks
from parkiq.runner import register

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)
SECOND = ("wd_eve", "we_eve", "event")
PAID = "paid-market (screening)"
CONTEXT = "free-parking area, context only"


def components(hex_ids: list[str]) -> list[list[str]]:
    """Edge-connected components (H3 k = 1) of a set of cells, deterministic order."""
    todo = set(hex_ids)
    out = []
    for start in sorted(hex_ids):
        if start not in todo:
            continue
        comp, stack = [], [start]
        todo.discard(start)
        while stack:
            h = stack.pop()
            comp.append(h)
            for n in h3.grid_disk(h, 1):
                if n in todo:
                    todo.discard(n)
                    stack.append(n)
        out.append(sorted(comp))
    return out


def market_evidence(sc: Any) -> dict[str, Any]:
    """Observed peak occupancy by area against the practical-capacity convention (ADR-0079).

    Market evidence only, kept apart from the model: it is not used to scale demand or supply.
    """
    pc = sc.practical_capacity
    path = sc.benchmark_occupancy_path
    if pc is None or path is None or not path.exists():
        return {}
    b = pd.read_csv(path)
    areas = []
    for r in b.itertuples():
        occ = float(r.peak_occupancy)
        areas.append(
            {
                "area": r.area,
                "peak_occupancy": occ,
                "vs_practical_capacity": round(occ - pc, 3),
                "status": "at or above practical capacity"
                if occ >= pc
                else "below practical capacity",
                "year": int(r.year),
                "source": r.source,
            }
        )
    return {
        "practical_capacity": pc,
        "note": str(b["note"].dropna().iloc[0]) if "note" in b and b["note"].notna().any() else "",
        "areas": areas,
    }


def paid_market_hexes(ctx: RunContext, hexes: gpd.GeoDataFrame) -> tuple[set[str], dict[str, int]]:
    """Hexes with paid parking within the largest walk band (see module docstring)."""
    cfg = ctx.cfg
    sc, dm = cfg.market.supply, cfg.market.demand
    written = set(ctx.store.written_layers())
    pts: list[gpd.GeoSeries] = []
    counts: dict[str, int] = {}
    if "OnStreetSegments" in written:
        ons = ctx.store.read_layer("OnStreetSegments")
        pts.append(ons.geometry.interpolate(0.5, normalized=True))
        counts["metered_block_faces"] = len(ons)
    if "SupplyFacilities" in written:
        f = ctx.store.read_layer("SupplyFacilities")
        fee = f["fee_flag"].fillna(0).astype(bool)
        drop = pd.Series(False, index=f.index)
        ovr = sc.paid_signal_overrides_path
        if ovr is not None and ovr.exists():  # reviewed signals that are not paid public parking
            o = pd.read_csv(ovr, dtype=str).fillna("")
            ids = set(o.loc[o["action"].str.lower().eq("drop"), "osm_id"])
            drop = (
                f["source_ids"].fillna("").map(lambda v: any(x in ids for x in str(v).split(";")))
            )
            fee &= ~drop
            counts["signals_overridden"] = int(drop.sum())
        op = pd.Series(False, index=f.index)
        if sc.paid_operators:
            # whole words only: "LAZ" must not match "Plaza"
            rx = "|".join(rf"\b(?:{p})(?!\w)" for p in sc.paid_operators)
            op = f["operator"].fillna("").str.contains(rx, flags=re.IGNORECASE, regex=True)
        op &= ~drop
        pts.append(f.loc[fee | op].geometry)
        counts["fee_tagged_facilities"] = int(fee.sum())
        counts["paid_operator_facilities"] = int((op & ~fee).sum())
    obs = sc.survey_observations_path
    if obs is not None and obs.exists():
        o = pd.read_csv(obs)
        if "outcome" in o.columns:
            o = o[o["outcome"].astype(str).str.lower().eq("rates posted")]
            if len(o):
                pts.append(
                    gpd.GeoSeries(gpd.points_from_xy(o["lon"], o["lat"]), crs=4326).to_crs(cfg.crs)
                )
            counts["survey_posted_price"] = len(o)
    if not pts:
        return set(), counts
    allp = gpd.GeoDataFrame(geometry=pd.concat(pts, ignore_index=True), crs=cfg.crs)
    graph = WalkGraph.from_layers(
        ctx.store.read_layer("WalkNodes"),
        ctx.store.read_layer("WalkEdges"),
        cfg.crs,
        cfg.market.network.walking_speed_m_s,
    )
    bands = [float(b) for b in dm.walk_shed_minutes]
    wts = {float(k): float(v) for k, v in dm.decay_weights.items()}
    _, _, w = allocate_matrix(allp, np.ones(len(allp)), hexes, graph, bands, wts, keep_weights=True)
    paid = set() if w is None else set(w["hex_id"])
    counts["indicator_points"] = len(allp)
    counts["paid_market_hexes"] = len(paid)
    return paid, counts


def _flags(z: gpd.GeoDataFrame | None) -> dict[str, int]:
    if z is None or z.empty:
        return {"zones": 0}
    big = ~z["below_min_lot_flag"].astype(bool)
    return {
        "zones": len(z),
        "zones_ge_min_lot": int(big.sum()),
        "single_hex_ge_min_lot": int((big & z["single_hex_flag"].astype(bool)).sum()),
        "single_anchor_ge_min_lot": int((big & z["single_anchor_flag"].astype(bool)).sum()),
        "curb_sensitive_ge_min_lot": int((big & z["curb_sensitive_flag"].astype(bool)).sum()),
    }


@register(
    "gap", deps=("demand", "supply"), reads=("market.demand", "market.supply"), milestone="M4"
)
def run_gap(ctx: RunContext) -> dict[str, Any]:
    """Gap per hex/daypart, paid-market mask and hot zones."""
    dm = ctx.cfg.market.demand
    d = ctx.store.read_table("Hex_Demand_Daypart")[["hex_id", "daypart", "demand_stalls"]]
    s = ctx.store.read_table("Hex_Supply_Daypart")
    g = d.merge(
        s[["hex_id", "daypart", "supply_stalls", "effective_supply_stalls", "curb_sensitive_flag"]],
        on=["hex_id", "daypart"],
        how="outer",
    ).fillna({"demand_stalls": 0.0, "supply_stalls": 0.0, "effective_supply_stalls": 0.0})
    g["gap_stalls"] = g["demand_stalls"] - g["effective_supply_stalls"]
    g["gap_ratio"] = np.where(
        g["effective_supply_stalls"] > 0, g["demand_stalls"] / g["effective_supply_stalls"], np.nan
    )
    g["rate_index"] = np.nan  # REAL column even while all-null
    hexes = ctx.store.read_layer("HexGrid").set_index("hex_id")
    paid, paid_counts = paid_market_hexes(ctx, hexes.reset_index())
    g["paid_market_flag"] = g["hex_id"].isin(paid)
    ctx.store.write_table(
        "Hex_Gap_Daypart",
        g[["hex_id", "daypart", "gap_stalls", "gap_ratio", "rate_index", "paid_market_flag"]],
    )
    wide = g.pivot_table(index="hex_id", columns="daypart", values="gap_stalls", aggfunc="sum")
    wide = wide.reindex(columns=list(DAYPARTS)).fillna(0.0)
    qual = wide[(wide["wd_day"] > 0) & (wide[list(SECOND)] > 0).any(axis=1)]
    min_lot = float(ctx.cfg.market.site.target_stalls_range[0])
    all_comps = components(list(qual.index))
    q_paid = [h for h in qual.index if h in paid]
    q_free = [h for h in qual.index if h not in paid]
    comps = [("P", c) for c in components(q_paid)] + [("C", c) for c in components(q_free)]

    curb = s[s["daypart"] == "wd_day"].set_index("hex_id")["curb_sensitive_flag"].fillna(0)
    wpath = ctx.run_dir / "demand_weights.parquet"
    weights = pd.read_parquet(wpath) if wpath.exists() else None
    anchors = ctx.store.read_layer("DemandAnchors", columns=["anchor_id", "demand_wd_day"])
    dwd = dict(zip(anchors["anchor_id"], anchors["demand_wd_day"], strict=True))
    places = None
    if dm.jurisdiction_places_path is not None:
        places = gpd.read_file(dm.jurisdiction_places_path).to_crs(ctx.cfg.crs)[
            ["NAME", "geometry"]
        ]
    share_max = float(dm.single_anchor_share or 1.0)
    rows = []
    for i, (cls, comp) in enumerate(comps, start=1):
        pos = qual.loc[comp]
        gap_pos = float(pos["wd_day"].clip(lower=0).sum())
        top_id, top_share = None, 0.0
        if weights is not None:
            wz = weights[weights["hex_id"].isin(comp)]
            contrib = (wz["w"] * wz["anchor_id"].map(dwd)).groupby(wz["anchor_id"]).sum()
            if len(contrib) and gap_pos > 0:
                top_id = str(contrib.idxmax())
                top_share = float(contrib.max() / gap_pos)
        geom = hexes.loc[comp].geometry.union_all()
        jur = ""
        if places is not None:
            jur = ";".join(sorted(set(places[places.intersects(geom)]["NAME"])))
        ncurb = int(curb.reindex(comp).fillna(0).astype(bool).sum())
        rows.append(
            {
                "zone_id": f"HZ-{cls}{i:04d}",
                "dayparts_positive": ";".join(dp for dp in DAYPARTS if (pos[dp] > 0).any()),
                "total_gap_stalls": gap_pos,
                "mean_rate_index": np.nan,
                "zone_size": len(comp),
                "single_hex_flag": len(comp) == 1,
                "top_anchor_id": top_id,
                "top_anchor_share": top_share,
                "single_anchor_flag": top_share > share_max,
                "curb_sensitive_hexes": ncurb,
                "curb_sensitive_flag": ncurb > 0,
                "jurisdictions": jur or "(unincorporated)",
                "below_min_lot_flag": gap_pos < min_lot,
                "zone_class": PAID if cls == "P" else CONTEXT,
                "paid_market_hexes": len(comp) if cls == "P" else 0,
                "geometry": geom,
            }
        )
    hz = gpd.GeoDataFrame(rows, geometry="geometry", crs=ctx.cfg.crs) if rows else None
    if hz is not None:
        ctx.store.write_layer("HotZones", hz, "DERIVED")
    scr = None if hz is None else hz[hz["zone_class"] == PAID]
    ctx_only = None if hz is None else hz[hz["zone_class"] == CONTEXT]
    n = 0 if scr is None else len(scr)
    write_checks(
        ctx,
        "gap",
        [
            Check(
                "QA-G01",
                "HotZones",
                "paid-market (screening) hot zones found",
                str(n),
                n,
                "> 0 (reported)",
                n > 0,
                severity="warning",
            ),
        ],
    )
    rep = {
        "paid_market": paid_counts,
        "before_mask": {
            "zones": len(all_comps),
            "zones_ge_min_lot": sum(
                1 for c in all_comps if qual.loc[c, "wd_day"].clip(lower=0).sum() >= min_lot
            ),
        },
        "screening": _flags(scr),
        "context_only": _flags(ctx_only),
        "hexes_qualifying": len(qual),
        "hexes_qualifying_paid": len(q_paid),
        "positive_gap_hexes": {dp: int((wide[dp] > 0).sum()) for dp in DAYPARTS},
    }
    rep["market_evidence"] = market_evidence(ctx.cfg.market.supply)
    (ctx.run_dir / "gap_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
