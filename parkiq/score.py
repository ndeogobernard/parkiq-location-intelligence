"""Phase G criteria, scoring and sensitivity (SCOPE §5.7; manual §10–11; ADR-0028, ADR-0029).

Criteria (raw, per Pass/Review candidate; walk times on the network from the site's
representative point):

* C01: net Σ weekday-day gap over hexes within 5 min, floored at 0 (net, because supply is
  already walk-allocated, ADR-0028).
* C02: net Σ (wd_eve + we_day + we_eve) gap within 5 min, floor 0.
* C03: Σ event gap within 8 min × events per year of venues within 8 min. Venues are excluded
  for Franklin (S10 disabled): no data → neutral.
* C04: rate index at the site, daypart-weighted (``c04_daypart_weights``). No rate surface until
  the round-1 survey → neutral.
* C05: effective competing stalls within 3 min (facilities + metered curb), excluding the
  site's own facility.
* C06: mean walk minutes to the top-3 anchors by total demand within 15 min; missing = 15.
* C07: land value per buildable stall (assessed land value ÷ stalls; a constant
  assessed-to-market ratio does not change normalized scores).
* C08: mean of corner (0/100), arterial frontage (0/100) and the AADT percentile of the
  busiest count station within 500 ft (null → left out of the mean); curb-cut score not
  collected (left out).
* C09: zoning certainty: ByRight 100, Conditional 60, Unknown 40; an existing lot on
  Prohibited zoning scores as Unknown (legal nonconforming status to verify).
* C10: pipeline projects within 5 min (S22 not configured → neutral).

Normalization: winsorize at p5/p95 (PERCENTILE.INC), min–max to 0–100, costs inverted. A
criterion with no data or zero variance scores 50 for every site and is logged; a single missing
value scores 50; weights are never renormalized (ADR-0028). Composite = Σ w·s per scenario; ranks
unique with ``parcel_id`` as tie-break. Rankings built with neutral criteria are PRELIMINARY.

Sensitivity: one-at-a-time ±25 % with the other weights rescaled to sum to 1, and flat-Dirichlet
random weights (α = 1, 1,000 draws, fixed seed; ADR-0029) → top-10 frequency, median rank, IQR.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.sparse import csgraph
from scipy.spatial import cKDTree

from parkiq import units
from parkiq.allocation import BATCH
from parkiq.config import DAYPARTS
from parkiq.runner import register
from parkiq.screen import walk_graph

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)

CRIT = [f"C{i:02d}" for i in range(1, 11)]
AADT_RADIUS_FT = 500.0  # C08: station "adjacent" to the site (ADR-0028 application)
EVE_WE = ("wd_eve", "we_day", "we_eve")


# --------------------------------------------------------------------------- pure functions
def normalize(
    x: np.ndarray, direction: str, pct: tuple[float, float] = (0.05, 0.95), const: float = 50.0
) -> tuple[np.ndarray, str]:
    """Winsorize → min–max 0–100 → invert costs. Missing values score ``const``."""
    x = np.asarray(x, dtype=float)
    ok = np.isfinite(x)
    if not ok.any():
        return np.full(len(x), const), "no data → neutral"
    lo, hi = np.percentile(x[ok], [pct[0] * 100, pct[1] * 100])  # linear = PERCENTILE.INC
    if hi <= lo:
        return np.full(len(x), const), "zero variance → neutral"
    s = (np.clip(x, lo, hi) - lo) / (hi - lo) * 100.0
    if direction == "Cost":
        s = 100.0 - s
    s = np.where(ok, s, const)
    note = f"{int((~ok).sum())} missing → {const:g}" if (~ok).any() else "ok"
    return s, note


def composite_rank(
    scores: np.ndarray, weights: np.ndarray, ids: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Composite (n) and unique ranks (1 = best; ties broken by id ascending)."""
    comp = scores @ weights
    order = np.lexsort((ids, -comp))
    rank = np.empty(len(comp), dtype=int)
    rank[order] = np.arange(1, len(comp) + 1)
    return comp, rank


def ranks_matrix(comp: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """Unique ranks for each row of a (draws × n) composite matrix (tie-break by id)."""
    id_order = np.argsort(np.argsort(ids, kind="stable"), kind="stable")  # id position
    key = -comp + id_order[None, :] * 1e-9  # ids break exact ties only
    order = np.argsort(key, axis=1, kind="stable")
    r = np.empty_like(order)
    rows = np.arange(comp.shape[0])[:, None]
    r[rows, order] = np.arange(1, comp.shape[1] + 1)[None, :]
    return r


def resolve_overlaps(
    geoms: gpd.GeoSeries, score: np.ndarray, ids: np.ndarray, min_share: float = 0.05
) -> dict[str, str]:
    """Candidates covering the same land: {superseded id: kept id} (ADR-0085).

    Two sites overlap when their shared area exceeds ``min_share`` of the smaller site. Sites are
    taken best score first (ties by id); a site overlapping one already kept is superseded by it.
    """
    order = np.lexsort((ids, -score))
    g = gpd.GeoDataFrame(geometry=geoms.to_numpy(), crs=geoms.crs)  # RangeIndex = position
    pairs = gpd.sjoin(g, g, predicate="intersects")
    left = pairs.index.to_numpy()
    right = pairs["index_right"].to_numpy()
    nbr: dict[int, list[int]] = {}
    for a, b in zip(left[left != right], right[left != right], strict=True):
        ga, gb = geoms.iloc[a], geoms.iloc[b]
        shared = ga.intersection(gb).area
        if shared > min_share * min(ga.area, gb.area):
            nbr.setdefault(int(a), []).append(int(b))
    kept: list[int] = []
    out: dict[str, str] = {}
    for i in order:
        hit = [k for k in kept if k in nbr.get(int(i), [])]
        if hit:
            out[str(ids[i])] = str(ids[hit[0]])
        else:
            kept.append(int(i))
    return out


def oat_weights(w: np.ndarray, i: int, factor: float) -> np.ndarray:
    """One-at-a-time weight change for criterion ``i``, others rescaled to sum to 1."""
    out = w.astype(float).copy()
    wi = min(max(w[i] * factor, 0.0), 1.0)
    rest = 1.0 - w[i]
    out = out * ((1.0 - wi) / rest) if rest > 0 else out
    out[i] = wi
    return out


# --------------------------------------------------------------------------- steps
def _candidates(ctx: RunContext) -> gpd.GeoDataFrame:
    c = ctx.store.read_layer("CandidateParcels")
    return c[c["screen_status"].isin(["Pass", "Review"])].reset_index(drop=True)


@register("criteria", deps=("walksheds",), reads=("criteria", "market.demand"), milestone="M5")
def run_criteria(ctx: RunContext) -> dict[str, Any]:
    """Raw C01–C10 per candidate → CandidateCriteria."""
    cfg = ctx.cfg
    c = _candidates(ctx)
    n = len(c)
    graph = walk_graph(ctx)
    crs = cfg.crs
    rp = c.geometry.representative_point()
    cxy = np.c_[rp.x.to_numpy(), rp.y.to_numpy()]
    cnode, csnap = graph.snap(cxy)
    c06 = cfg.criteria.c06
    limit = max(8.0, float(c06["search_minutes"]))

    # targets: hexes, facilities, curb, anchors (snap each once)
    hexes = ctx.store.read_layer("HexGrid")
    gap = ctx.store.read_table("Hex_Gap_Daypart")
    wide = gap.pivot_table(index="hex_id", columns="daypart", values="gap_stalls", aggfunc="sum")
    wide = wide.reindex(index=hexes["hex_id"], columns=list(DAYPARTS)).fillna(0.0)
    rate = gap.pivot_table(index="hex_id", columns="daypart", values="rate_index", aggfunc="mean")
    hc = hexes.geometry.centroid
    h_node, h_snap = graph.snap(np.c_[hc.x.to_numpy(), hc.y.to_numpy()])

    fac = ctx.store.read_layer("SupplyFacilities")
    cap = fac["capacity_stated"].fillna(fac["capacity_est"]).fillna(0.0).to_numpy(dtype=float)
    share = float(cfg.market.supply.private_effective_share)
    eff = np.where(fac["private_flag"].fillna(0).astype(bool), cap * share, cap)
    fpt = fac.geometry.representative_point()
    f_node, f_snap = graph.snap(np.c_[fpt.x.to_numpy(), fpt.y.to_numpy()])
    own = gpd.sjoin(
        gpd.GeoDataFrame(geometry=fpt, crs=fac.crs), c[["geometry"]], predicate="within"
    )
    own_of = own.groupby("index_right").apply(lambda g: set(g.index)).to_dict()
    ons = ctx.store.read_layer("OnStreetSegments", columns=["stalls_est"])
    om = ons.geometry.interpolate(0.5, normalized=True)
    o_node, o_snap = graph.snap(np.c_[om.x.to_numpy(), om.y.to_numpy()])
    o_st = ons["stalls_est"].fillna(0.0).to_numpy(dtype=float)

    an = ctx.store.read_layer("DemandAnchors")
    an_dem = an[[f"demand_{d}" for d in DAYPARTS]].fillna(0.0).sum(axis=1).to_numpy()
    a_node, a_snap = graph.snap(np.c_[an.geometry.x.to_numpy(), an.geometry.y.to_numpy()])

    venues = ctx.store.read_layer("Venues")
    venues = venues[venues["events_per_year"].notna()] if len(venues) else venues

    raw = np.full((n, 10), np.nan)
    notes: list[dict[str, Any]] = [{} for _ in range(n)]
    for start in range(0, n, BATCH):
        sl = slice(start, start + BATCH)
        dist = csgraph.dijkstra(graph.csr, directed=False, indices=cnode[sl], limit=limit)
        for k, j in enumerate(range(start, min(start + BATCH, n))):
            d = dist[k] + csnap[j]
            th = d[h_node] + h_snap
            in5 = th <= 5.0
            raw[j, 0] = max(0.0, float(wide["wd_day"].to_numpy()[in5].sum()))
            raw[j, 1] = max(0.0, float(wide[list(EVE_WE)].to_numpy()[in5].sum()))
            if len(venues):
                in8 = th <= 8.0
                vn, vs = graph.snap(
                    np.c_[venues.geometry.x.to_numpy(), venues.geometry.y.to_numpy()]
                )
                ev = venues["events_per_year"].to_numpy(dtype=float)[(d[vn] + vs) <= 8.0].sum()
                raw[j, 2] = max(0.0, float(wide["event"].to_numpy()[in8].sum())) * ev
            tf = d[f_node] + f_snap
            sel = tf <= 3.0
            mine = own_of.get(j, set())
            if mine:
                sel[list(mine)] = False
            to = d[o_node] + o_snap
            raw[j, 4] = float(eff[sel].sum() + o_st[to <= 3.0].sum())
            ta = d[a_node] + a_snap
            reach = np.flatnonzero(ta <= float(c06["search_minutes"]))
            top = reach[np.argsort(-an_dem[reach])][: int(c06["top_n"])]
            mins = list(ta[top]) + [float(c06["missing_minutes"])] * (int(c06["top_n"]) - len(top))
            raw[j, 5] = float(np.mean(mins))
            notes[j]["top_anchors"] = [str(an["anchor_id"].iloc[t]) for t in top]
            notes[j]["own_facilities_excluded"] = len(mine)

    # C04: rate index at the site (hex containing the representative point)
    w04 = cfg.criteria.c04_daypart_weights or {}
    if rate.notna().to_numpy().any() and w04:
        hx = gpd.sjoin(
            gpd.GeoDataFrame(geometry=rp, crs=c.crs),
            hexes[["hex_id", "geometry"]],
            predicate="within",
        )
        r = rate.reindex(hx["hex_id"]).reindex(columns=list(w04)).to_numpy()
        ww = np.array([w04[dp] for dp in w04])
        raw[hx.index.to_numpy(), 3] = np.nansum(r * ww, axis=1) / np.where(
            np.isfinite(r), ww, 0
        ).sum(axis=1)

    # C07: land value per buildable stall
    stalls = c["stalls"].to_numpy(dtype=float)
    lv = c["land_value"].to_numpy(dtype=float)
    raw[:, 6] = np.where((stalls > 0) & (lv > 0), lv / np.maximum(stalls, 1), np.nan)

    # C08: access: corner, arterial, AADT percentile within 500 ft
    tc = ctx.store.read_layer("TrafficCounts")
    tc = tc[tc["aadt"].notna()]
    aadt_pct = np.full(n, np.nan)
    if len(tc):
        pct = tc["aadt"].rank(pct=True).to_numpy() * 100.0
        tree = cKDTree(np.c_[tc.geometry.x.to_numpy(), tc.geometry.y.to_numpy()])
        rad = units.m_to_crs(units.ft_to_m(AADT_RADIUS_FT), crs)
        bnd = c.geometry.boundary
        for j in range(n):
            near = tree.query_ball_point(cxy[j], rad + np.sqrt(c.geometry.iloc[j].area))
            near = [q for q in near if bnd.iloc[j].distance(tc.geometry.iloc[q]) <= rad]
            if near:
                aadt_pct[j] = float(max(pct[q] for q in near))
    parts = np.c_[
        c["corner_flag"].fillna(0).astype(bool).to_numpy() * 100.0,
        c["arterial_flag"].fillna(0).astype(bool).to_numpy() * 100.0,
        aadt_pct,
    ]
    raw[:, 7] = np.nanmean(parts, axis=1)

    # C09: zoning certainty
    sc = cfg.criteria.c09_scores
    zs = c["zoning_screen"].fillna("Unknown").astype(str)
    zs = zs.where(zs != "Prohibited", "Unknown")  # existing lots only (verify nonconforming)
    raw[:, 8] = zs.map(lambda v: float(sc.get(v, sc.get("Unknown", 40)))).to_numpy()

    # C10: pipeline (S22) not configured → no data (neutral)
    out = pd.DataFrame(raw, columns=[f"{x.lower()}_raw" for x in CRIT])
    out.insert(0, "parcel_id", c["parcel_id"].to_numpy())
    out["notes_json"] = [json.dumps(x) for x in notes]
    ctx.store.write_table("CandidateCriteria", out)
    missing = {x: int(np.isnan(raw[:, i]).sum()) for i, x in enumerate(CRIT)}
    rep = {
        "candidates": n,
        "missing_raw": missing,
        "aadt_matched": int(np.isfinite(aadt_pct).sum()),
    }
    (ctx.run_dir / "criteria_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def _scored(ctx: RunContext) -> tuple[gpd.GeoDataFrame, np.ndarray, dict[str, str]]:
    cfg = ctx.cfg
    c = _candidates(ctx)
    cr = ctx.store.read_table("CandidateCriteria").set_index("parcel_id").reindex(c["parcel_id"])
    norm = cfg.criteria.normalization
    s = np.zeros((len(c), 10))
    notes: dict[str, str] = {}
    for i, x in enumerate(CRIT):
        s[:, i], notes[x] = normalize(
            cr[f"{x.lower()}_raw"].to_numpy(dtype=float),
            cfg.criteria.criteria[x].direction,
            tuple(norm.winsor_percentiles),  # type: ignore[arg-type]
            float(norm.constant_score),
        )
    return c, s, notes


@register("suitability", deps=("criteria",), reads=("weights", "criteria"), milestone="M5")
def run_suitability(ctx: RunContext) -> dict[str, Any]:
    """Normalize, composite and rank per scenario → SiteScores (PRELIMINARY if neutral criteria)."""
    cfg = ctx.cfg
    c, s, notes = _scored(ctx)
    # the same land appears in one candidate only: keep the higher Balanced score (ADR-0085)
    wb = cfg.weights.scenarios.get("Balanced") or next(iter(cfg.weights.scenarios.values()))
    comp_b, _ = composite_rank(
        s, np.array([wb[x] for x in CRIT]), c["parcel_id"].astype(str).to_numpy()
    )
    sup = resolve_overlaps(c.geometry, comp_b, c["parcel_id"].astype(str).to_numpy())
    if sup:
        allc = ctx.store.read_layer("CandidateParcels")
        hit = allc["parcel_id"].isin(list(sup))
        allc.loc[hit, "superseded_by"] = allc.loc[hit, "parcel_id"].map(sup)
        allc.loc[hit, "screen_reason"] = (
            "SUPERSEDED: superseded by " + allc.loc[hit, "superseded_by"]
        )
        allc.loc[hit, "screen_status"] = "Fail"
        ctx.store.write_layer("CandidateParcels", allc, None)
        c, s, notes = _scored(ctx)  # normalize over the remaining candidates
    cr = ctx.store.read_table("CandidateCriteria").set_index("parcel_id").reindex(c["parcel_id"])
    neutral = [x for x, v in notes.items() if "neutral" in v]
    prelim = bool(neutral)
    ids = c["parcel_id"].astype(str).to_numpy()
    frames = []
    for scen, wd in cfg.weights.scenarios.items():
        w = np.array([wd[x] for x in CRIT])
        comp, rank = composite_rank(s, w, ids)
        f = gpd.GeoDataFrame({"parcel_id": ids, "scenario": scen}, geometry=c.geometry, crs=c.crs)
        for i, x in enumerate(CRIT):
            f[f"{x.lower()}_raw"] = cr[f"{x.lower()}_raw"].to_numpy()
            f[f"{x.lower()}_s"] = np.round(s[:, i], 3)
        f["composite"] = np.round(comp, 3)
        f["rank"] = rank
        f["preliminary_flag"] = prelim
        frames.append(f)
    out = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=c.crs)
    ctx.store.write_layer("SiteScores", out, "DERIVED")
    rep = {
        "candidates": len(c),
        "superseded": sup,
        "normalization": notes,
        "neutral_criteria": neutral,
        "weights_renormalized": False,
        "ranking": "PRELIMINARY" if prelim else "final",
    }
    (ctx.run_dir / "suitability_report.json").write_text(
        json.dumps(rep, indent=1), encoding="utf-8"
    )
    return rep


@register("sensitivity", deps=("suitability",), reads=("weights", "criteria"), milestone="M5")
def run_sensitivity(ctx: RunContext) -> dict[str, Any]:
    """OAT ±25 % and flat-Dirichlet rank stability → RankStability."""
    cfg = ctx.cfg
    c, s, _ = _scored(ctx)
    ids = c["parcel_id"].astype(str).to_numpy()
    sp = cfg.criteria.sensitivity
    top_n = int(sp.get("top_n", 10))
    ranks: dict[str, np.ndarray] = {}
    oat_max = np.zeros(len(c), dtype=int)
    for scen, wd in cfg.weights.scenarios.items():
        w = np.array([wd[x] for x in CRIT])
        _, base = composite_rank(s, w, ids)
        ranks[scen] = base
        for i in range(10):
            for f in (1 + sp["oat_pct"], 1 - sp["oat_pct"]):
                _, r = composite_rank(s, oat_weights(w, i, f), ids)
                oat_max = np.maximum(oat_max, np.abs(r - base))
    rng = np.random.default_rng(int(sp["seed"]))
    draws = rng.dirichlet(np.full(10, float(sp["alpha"])), int(sp["draws"]))
    rm = ranks_matrix(draws @ s.T, ids)
    out = pd.DataFrame(
        {
            "parcel_id": ids,
            **{f"rank_{k}": v for k, v in ranks.items()},
            "top10_freq": (rm <= top_n).mean(axis=0),
            "median_rank": np.median(rm, axis=0),
            "iqr_rank": np.percentile(rm, 75, axis=0) - np.percentile(rm, 25, axis=0),
            "oat_max_change": oat_max,
        }
    )
    ctx.store.write_table("RankStability", out)
    rep = {
        "candidates": len(c),
        "draws": int(sp["draws"]),
        "alpha": float(sp["alpha"]),
        "seed": int(sp["seed"]),
        "oat_pct": float(sp["oat_pct"]),
        "max_oat_change": int(oat_max.max()) if len(oat_max) else 0,
    }
    (ctx.run_dir / "sensitivity_report.json").write_text(
        json.dumps(rep, indent=1), encoding="utf-8"
    )
    return rep
