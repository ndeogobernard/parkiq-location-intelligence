"""Phase E screen and Phase F walk sheds (SCOPE §5.5–5.6; manual §9–10; M5).

Screen (every parcel is evaluated; each site gets a status and ALL failing reasons):

* **hot-zone rule** — network walk ≤ 8 min to a PAID-MARKET screening hot zone (``HZ-P``,
  ADR-0075); context-only zones never qualify a parcel.
* **land use** — Vacant / SurfaceParking / improvement ratio < max / auto-oriented, plus the
  crosswalk special rules (600–699 exempt owner → Review; code 456 surface-vs-garage check).
* **existing surface lots** (ADR-0063) — zoning Fail (incl. Zone A) and design overlays become
  Review; they are not failed on shape (M5 rule) and their stalls come from the lot polygon
  (area × layout efficiency ÷ stall area × ``supply.surface_capacity_factor``, ADR-0067).
* **parcel assembly** (M5 rule) — contiguous land-use-eligible parcels with the same normalized
  owner inside the 8-minute reach are merged BEFORE the size/stall screen; an assembly larger than
  ``max_parcel_sqft`` falls back to its component parcels (reported).
* **size + stall range** (ADR-0031, stalls rounded down ADR-0049), **shape** (rectangularity,
  ADR-0025), **frontage** (ADR-0026, ``frontage_buffer_ft``), excluded use, floodway, slope.
  Frontage, corner and slope are measured only for sites inside the 8-minute reach (all others
  already fail HOTZONE; reported).
* PERMIT (S22 pipeline) is not applied while S22 is not configured (logged).

Status: Fail if any reason; Review if none but zoning is Review/Unknown, the site is an existing
lot, or land value is missing; else Pass. Pass and Review continue to scoring.

Walk sheds: 3/5/8-minute network polygons per Pass/Review candidate = reachable edges buffered by
15 m (ADR-0027).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy import sparse
from scipy.sparse import csgraph

from parkiq import units
from parkiq.allocation import BATCH, WalkGraph
from parkiq.demand import norm_owner
from parkiq.qaqc import Check, write_checks
from parkiq.runner import register

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)

HOTZONE_MINUTES = 8.0  # SCOPE §5.5 hot-zone rule (8-minute walk)
DRIVE = ("residential", "unclassified", "tertiary", "secondary", "primary", "trunk")
ARTERIAL = ("primary", "secondary", "trunk")
SHED_BUFFER_M = 15.0  # ADR-0027
EXISTING = (
    "existing surface lot — possible legal nonconforming use; verify grandfathered status "
    "(§3359.27 pre-1999 exception / nonconforming-use rules)"
)
ZS_ORDER = {"Prohibited": 0, "Unknown": 1, "Conditional": 2, "ByRight": 3}
SCOPE_POOL = (40, 200)  # SCOPE §5.5 expectation (ADR-0030: report, never auto-adjust)


def walk_graph(ctx: RunContext) -> WalkGraph:
    """Walk graph of the run."""
    return WalkGraph.from_layers(
        ctx.store.read_layer("WalkNodes"),
        ctx.store.read_layer("WalkEdges"),
        ctx.cfg.crs,
        ctx.cfg.market.network.walking_speed_m_s,
    )


def hotzone_minutes(
    graph: WalkGraph, zones: gpd.GeoDataFrame, hexes: gpd.GeoDataFrame, pts: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Walk minutes from each point to the nearest zone hex centroid, and that zone's row."""
    if zones.empty:
        return np.full(len(pts), np.inf), np.full(len(pts), -1)
    zh = gpd.sjoin(
        gpd.GeoDataFrame(geometry=hexes.geometry.centroid, crs=hexes.crs),
        zones[["geometry"]].reset_index(drop=True),
        predicate="within",
    )
    cent = np.c_[zh.geometry.x.to_numpy(), zh.geometry.y.to_numpy()]
    src, _ = graph.snap(cent)
    dist, _, sources = csgraph.dijkstra(
        graph.csr,
        directed=False,
        indices=src,
        limit=HOTZONE_MINUTES,
        min_only=True,
        return_predecessors=True,
    )
    zone_of_node = pd.Series(zh["index_right"].to_numpy(), index=src).groupby(level=0).first()
    node, snap = graph.snap(pts)
    t = dist[node] + snap
    z = zone_of_node.reindex(sources[node]).fillna(-1).to_numpy()
    return t, np.where(np.isfinite(t), z, -1).astype(int)


def assemble(sites: gpd.GeoDataFrame) -> np.ndarray:
    """Component label per row: contiguous parcels with the same normalized owner."""
    n = len(sites)
    own = sites["owner"].map(norm_owner).to_numpy()
    idx = np.flatnonzero(own != "")
    if len(idx) < 2:
        return np.arange(n)
    sub = sites.iloc[idx][["geometry"]].reset_index(drop=True)
    j = gpd.sjoin(sub, sub, predicate="intersects")
    a = idx[j.index.to_numpy()]
    b = idx[j["index_right"].to_numpy()]
    keep = (a != b) & (own[a] == own[b])
    m = sparse.coo_matrix((np.ones(int(keep.sum())), (a[keep], b[keep])), shape=(n, n))
    _, labels = csgraph.connected_components(m, directed=False)
    return np.asarray(labels)


def _bearings(seg: Any, min_len: float) -> list[float]:
    out = []
    for part in getattr(seg, "geoms", [seg]):
        c = np.asarray(part.coords) if hasattr(part, "coords") else np.empty((0, 2))
        if len(c) >= 2 and shapely.length(part) > min_len:
            dx, dy = c[-1] - c[0]
            out.append(float(np.degrees(np.arctan2(dy, dx)) % 180))
    return out


def frontage(sites: gpd.GeoDataFrame, edges: gpd.GeoDataFrame, buffer_crs: float) -> pd.DataFrame:
    """Frontage length (CRS units), corner and arterial flags per site (ADR-0026).

    Frontage = length of the site boundary within ``buffer_crs`` of a drive-street centerline
    (service roads, alleys and footways excluded). Corner = frontage on two streets with different
    names, or on stretches whose bearings differ by ≥ 45°. Arterial = any frontage on a
    primary/secondary/trunk street.
    """
    out = pd.DataFrame({"frontage": 0.0, "corner": False, "arterial": False}, index=sites.index)
    if sites.empty:
        return out
    e = edges[edges["highway"].astype(str).isin(DRIVE)].reset_index(drop=True)
    e = e.assign(geometry=e.geometry.buffer(buffer_crs, cap_style="flat"))
    bnd = gpd.GeoDataFrame(
        {"sid": sites.index.to_numpy()}, geometry=sites.geometry.boundary.to_numpy(), crs=sites.crs
    )  # positional: site labels need not be 0..n-1
    j = gpd.sjoin(bnd, e[["highway", "name", "geometry"]], predicate="intersects")
    if j.empty:
        return out
    seg = shapely.intersection(j.geometry.to_numpy(), e.geometry.to_numpy()[j["index_right"]])
    j = j.assign(seg=seg, L=shapely.length(seg))
    j = j[j["L"] > 0]
    for sid, g in j.groupby("sid"):
        out.at[sid, "frontage"] = float(shapely.length(shapely.union_all(g["seg"].to_numpy())))
        out.at[sid, "arterial"] = bool(g["highway"].astype(str).isin(ARTERIAL).any())
        names = {str(v) for v in g["name"].dropna() if str(v) not in ("", "nan")}
        corner = len(names) >= 2
        if not corner:
            ang = [a for s_ in g["seg"] for a in _bearings(s_, buffer_crs)]
            corner = any(
                min(abs(a - b), 180 - abs(a - b)) >= 45
                for i, a in enumerate(ang)
                for b in ang[i + 1 :]
            )
        out.at[sid, "corner"] = corner
    return out


def _slope(ctx: RunContext, geoms: gpd.GeoSeries) -> np.ndarray:
    import rasterio
    from rasterio import features

    tif = ctx.run_dir / "rasters" / "Slope_pct.tif"
    if not tif.exists() or len(geoms) == 0:
        return np.full(len(geoms), np.nan)
    with rasterio.open(tif) as src:
        arr = src.read(1, masked=True).filled(np.nan)
        lab = features.rasterize(
            ((g, k + 1) for k, g in enumerate(geoms)),
            out_shape=arr.shape,
            transform=src.transform,
            fill=0,
            dtype="int32",
            all_touched=True,
        )
    ok = (lab > 0) & ~np.isnan(arr)
    s = np.bincount(lab[ok], weights=arr[ok], minlength=len(geoms) + 1)
    n = np.bincount(lab[ok], minlength=len(geoms) + 1)
    return np.asarray(np.where(n > 0, s / np.maximum(n, 1), np.nan)[1:])


def _cover(parcels: gpd.GeoDataFrame, layer: gpd.GeoDataFrame, idx: np.ndarray) -> pd.Series:
    """Area of ``layer`` inside each parcel (CRS units²), for parcel rows ``idx``."""
    if layer.empty or len(idx) == 0:
        return pd.Series(0.0, index=idx)
    s = gpd.GeoDataFrame({"pid": idx}, geometry=parcels.geometry.to_numpy()[idx], crs=parcels.crs)
    lay = layer[["geometry"]].reset_index(drop=True)
    j = gpd.sjoin(s, lay, predicate="intersects")
    if j.empty:
        return pd.Series(0.0, index=idx)
    inter = shapely.intersection(j.geometry.to_numpy(), lay.geometry.to_numpy()[j["index_right"]])
    a = pd.Series(shapely.area(inter), index=j["pid"].to_numpy()).groupby(level=0).sum()
    return a.reindex(idx).fillna(0.0)


def _zoning_tag(reason: str) -> str:
    if "limitation text" in reason:
        return "limitation text applies"
    if "near digitized" in reason:
        return "near Zone A/B boundary"
    if "jurisdiction" in reason and "not in table" in reason:
        return "jurisdiction not in zoning table"
    if "overlay:" in reason:
        return "design overlay"
    return "Unknown/low-confidence"


@register(
    "screen", deps=("gap",), reads=("market.site", "market.supply", "sources.S01"), milestone="M5"
)
def run_screen(ctx: RunContext) -> dict[str, Any]:
    """Screen every parcel; write CandidateParcels (all evaluated sites, all reasons)."""
    cfg = ctx.cfg
    site = cfg.market.site
    crs = cfg.crs
    p = ctx.store.read_layer("Parcels").reset_index(drop=True)
    n = len(p)
    sqft = p["lot_sqft"].to_numpy(dtype=float)
    low = (p["improvement_value_ratio"] < float(site.improvement_ratio_max or 0)).fillna(False)
    low = low.to_numpy(dtype=bool)
    parea = p.geometry.area.to_numpy()

    # ---- crosswalk special rules
    rule = np.full(n, "", dtype=object)
    s01 = cfg.sources.get("S01")
    xw_path = s01.options.get("land_use_crosswalk_path") if s01 is not None else None
    if xw_path:
        xw = pd.read_csv(xw_path, dtype=str).fillna("")
        if "special_rule" in xw.columns:
            m = dict(zip(xw["county_code"], xw["special_rule"], strict=True))
            rule = p["land_use_code"].astype(str).map(m).fillna("").to_numpy()

    # ---- hot-zone reach first: everything expensive is measured only inside it
    graph = walk_graph(ctx)
    hz = ctx.store.read_layer("HotZones")
    zones = hz[hz["zone_class"].astype(str).str.startswith("paid")].reset_index(drop=True)
    hexes = ctx.store.read_layer("HexGrid")
    rp = p.geometry.representative_point()
    t_hz, z_hz = hotzone_minutes(graph, zones, hexes, np.c_[rp.x.to_numpy(), rp.y.to_numpy()])
    inside = gpd.sjoin(
        gpd.GeoDataFrame(geometry=rp, crs=p.crs), zones[["geometry"]], predicate="within"
    )
    t_hz[inside.index.to_numpy()] = 0.0
    z_hz[inside.index.to_numpy()] = inside["index_right"].to_numpy()
    reach = t_hz <= HOTZONE_MINUTES
    ridx = np.flatnonzero(reach)
    log.info("parcels within %.0f min of a paid-market hot zone: %d", HOTZONE_MINUTES, len(ridx))

    # ---- existing surface lots (ADR-0063), inside the reach
    osm = ctx.store.read_layer("ParkingOSM")
    osm = osm[osm.geom_type.isin(["Polygon", "MultiPolygon"])]
    surf = osm[osm["parking"].fillna("surface").isin(["surface", "lane"])]
    garage = osm[osm["parking"].isin(["multi-storey", "underground", "rooftop"])]
    bld = ctx.store.read_layer("Buildings", columns=["bldg_id"])
    area_surf = _cover(p, surf, ridx)
    share_surf = area_surf / parea[ridx]
    pk456 = ridx[rule[ridx] == "confirm_surface_parking"]
    c_gar = _cover(p, garage, pk456) / parea[pk456]
    c_bld = _cover(p, bld, pk456) / parea[pk456]
    existing = np.zeros(n, dtype=bool)
    hard: dict[int, list[str]] = {}
    review: dict[int, list[str]] = {}
    for i in pk456:
        if not low[i]:
            continue
        if c_gar[i] > 0.25 or c_bld[i] > 0.5:
            hard.setdefault(i, []).append("code 456: parking structure")
        elif share_surf[i] >= 0.5 and c_bld[i] <= 0.2:
            existing[i] = True
        else:
            review.setdefault(i, []).append("code 456: surface vs garage unresolved")
    existing[share_surf[share_surf >= 0.5].index.to_numpy()] = True

    excluded = p["excluded_use_flag"].fillna(0).astype(bool).to_numpy()
    eligible = (
        p["land_use_class"].isin(["Vacant", "SurfaceParking"]).to_numpy()
        | low
        | p["auto_oriented_flag"].fillna(0).astype(bool).to_numpy()
        | existing
    )
    exempt_low = (rule == "exempt_low_improvement_review") & (
        (p["assessed_improvement_value"].fillna(-1).to_numpy() == 0) | low
    )

    # ---- parcel assembly inside the reach (M5 rule)
    labels = np.arange(n)
    pool = np.flatnonzero(reach & (eligible | exempt_low) & ~excluded)
    if len(pool):
        labels[pool] = n + assemble(p.iloc[pool])
    lab_s = pd.Series(labels)
    cnt = lab_s.map(lab_s.value_counts()).to_numpy()
    area_by = pd.Series(sqft).groupby(labels).transform("sum").to_numpy()
    too_big = (cnt > 1) & (area_by > site.max_parcel_sqft)
    fallback = int(lab_s[too_big].nunique())
    labels[too_big] = np.flatnonzero(too_big)
    site_of = pd.factorize(labels)[0]
    ns = int(site_of.max()) + 1
    members = pd.Series(np.arange(n)).groupby(site_of).apply(list)
    msize = members.map(len).to_numpy()
    first = members.map(lambda m: m[0]).to_numpy()
    multi = np.flatnonzero(msize > 1)
    log.info(
        "assemblies: %d sites from %d parcels (%d too large → components)",
        len(multi),
        int(msize[multi].sum()),
        fallback,
    )

    # ---- site table (aggregated over components)
    def agg(values: Any, how: str) -> np.ndarray:
        return np.asarray(pd.Series(values).groupby(site_of).agg(how).to_numpy())

    pgeo = p.geometry.to_numpy()
    geoms = pgeo[first].copy()
    pid = p["parcel_id"].astype(str).to_numpy()
    site_id = pid[first].astype(object)
    for q in multi.tolist():
        geoms[q] = shapely.union_all(pgeo[members.iloc[q]])
        site_id[q] = "ASM:" + min(pid[members.iloc[q]])
    sgeo = gpd.GeoSeries(geoms, crs=p.crs)
    lot = agg(sqft, "sum")
    lv = p["assessed_land_value"].to_numpy(dtype=float)
    land_value = np.asarray(pd.Series(lv).groupby(site_of).sum(min_count=1).to_numpy())
    ex_site = agg(existing, "max").astype(bool)
    reach_site = agg(reach, "max").astype(bool)
    t_site = agg(t_hz, "min")
    zone_site = np.full(ns, -1)
    fin = np.isfinite(t_hz)
    if fin.any():
        best = pd.DataFrame({"s": site_of[fin], "t": t_hz[fin], "z": z_hz[fin]}).sort_values("t")
        b1 = best.drop_duplicates("s")
        zone_site[b1["s"].to_numpy()] = b1["z"].to_numpy()
    rect = shapely.area(shapely.oriented_envelope(geoms))
    shape_index = np.where(rect > 0, sgeo.area.to_numpy() / np.where(rect > 0, rect, 1), np.nan)
    excl_site = agg(excluded, "max").astype(bool)
    elig_site = agg(eligible | exempt_low, "max").astype(bool)
    exlow_site = agg(exempt_low, "max").astype(bool)

    # stalls: new-lot layout rounded down (ADR-0049) or existing-lot polygon (ADR-0067)
    new_stalls = np.floor(
        lot * (1 - site.setback_landscape_pct) * site.layout_efficiency / site.stall_area_sqft_gross
    )
    fac = float(cfg.market.supply.surface_capacity_factor or 1.0)
    surf_area = np.zeros(n)
    surf_area[area_surf.index.to_numpy()] = area_surf.to_numpy()
    ex_sqft = units.crs_area_to_sqft(1.0, crs) * agg(surf_area, "sum")
    ex_stalls = np.floor(ex_sqft * site.layout_efficiency / site.stall_area_sqft_gross * fac)
    stalls = np.where(ex_site, ex_stalls, new_stalls)
    basis = np.where(ex_site, "existing lot polygon", "new lot layout")

    # frontage / corner / slope inside the reach only (ADR-0026)
    rs_idx = np.flatnonzero(reach_site)
    rs = gpd.GeoDataFrame(geometry=sgeo.iloc[rs_idx].to_numpy(), index=rs_idx, crs=p.crs)
    edges = ctx.store.read_layer("WalkEdges", columns=["highway", "name"])
    buf = units.m_to_crs(units.ft_to_m(float(site.frontage_buffer_ft or 0)), crs)
    fr = frontage(rs, edges, buf)
    to_ft = units.crs_to_m(1.0, crs) / 0.3048
    front = np.full(ns, np.nan)
    corner = np.zeros(ns, dtype=bool)
    arterial = np.zeros(ns, dtype=bool)
    front[rs_idx] = fr["frontage"].to_numpy() * to_ft
    corner[rs_idx] = fr["corner"].to_numpy(dtype=bool)
    arterial[rs_idx] = fr["arterial"].to_numpy(dtype=bool)
    slope = np.full(ns, np.nan)
    slope[rs_idx] = _slope(ctx, rs.geometry)

    # floodway, SFHA, brownfield (all sites)
    sdf = gpd.GeoDataFrame(geometry=sgeo, crs=p.crs)

    def hits(layer: gpd.GeoDataFrame) -> np.ndarray:
        out_ = np.zeros(ns, dtype=bool)
        if len(layer):
            out_[gpd.sjoin(sdf, layer[["geometry"]], predicate="intersects").index.unique()] = True
        return out_

    fh = ctx.store.read_layer("FloodHazard")
    floodway = hits(fh[fh["floodway_flag"].fillna(0).astype(bool)])
    sfha = hits(fh[fh["sfha_flag"].fillna(0).astype(bool)])
    env = ctx.store.read_layer("EnvSites")
    brownfield = hits(env[env["brownfield_flag"].fillna(0).astype(bool)])

    # zoning (least permissive component), Zone A
    zs = p["zoning_screen"].fillna("Unknown").astype(str).to_numpy()
    zst = p["zoning_status"].fillna("Review").astype(str).to_numpy()
    zrank = np.array([ZS_ORDER.get(v, 1) for v in zs])
    zs_site = np.array(list(ZS_ORDER))[agg(zrank, "min").astype(int)]
    zone_a = agg((p["parking_zone"] == "A").to_numpy(), "max").astype(bool)
    zcode = p["zoning_code"].fillna("").astype(str).to_numpy()
    zreason = p["zoning_reason"].fillna("").astype(str).to_numpy()
    lu = p["land_use_class"].fillna("").astype(str).to_numpy()

    # ---- reasons per site
    lo, hi = site.min_parcel_sqft, site.max_parcel_sqft
    smin, smax = site.target_stalls_range
    reasons: list[list[str]] = []
    status: list[str] = []
    for k in range(ns):
        mm = members.iloc[k]
        h = [r for i in mm for r in hard.get(i, [])]
        rv = [r for i in mm for r in review.get(i, [])]
        nl: list[str] = []
        if not reach_site[k]:
            h.append(f"HOTZONE: not within {HOTZONE_MINUTES:.0f} min of a paid-market hot zone")
        if lot[k] < lo or lot[k] > hi:
            h.append(f"SIZE: {lot[k]:,.0f} sq ft outside {lo:,.0f}–{hi:,.0f}")
        elif stalls[k] < smin or stalls[k] > smax:
            h.append(f"STALLS: {stalls[k]:.0f} outside {smin}–{smax} ({basis[k]})")
        if not ex_site[k] and shape_index[k] < site.min_shape_index:
            h.append(f"SHAPE: {shape_index[k]:.2f} < {site.min_shape_index}")
        if reach_site[k] and front[k] < site.min_frontage_ft:
            h.append(f"FRONTAGE: {front[k]:.0f} ft < {site.min_frontage_ft:.0f}")
        if excl_site[k]:
            h.append("EXCLUDED_USE: park/cemetery/ROW/utility")
        if floodway[k]:
            h.append("FLOODWAY")
        if slope[k] >= site.max_slope_pct:
            h.append(f"SLOPE: mean {slope[k]:.1f}% >= {site.max_slope_pct}%")
        if not elig_site[k]:
            nl.append(
                f"LANDUSE: {lu[mm[0]]} with improvement ratio >= {site.improvement_ratio_max}"
            )
        if exlow_site[k]:
            rv.append("tax-exempt owner, vacant/low improvement — possible ground lease")
        zf = sorted({zcode[i] for i in mm if zst[i] == "Fail"})
        if zf:
            nl.append("ZONING: prohibits a new lot (" + ", ".join(zf) + ")")
        zr = [i for i in mm if zst[i] == "Review"]
        if zr:
            rv.append("zoning: " + _zoning_tag(zreason[zr[0]]))
        if not land_value[k] > 0:
            rv.append("missing land value")
        if h or (nl and not ex_site[k]):
            status.append("Fail")
            reasons.append(h + nl)
            continue
        if ex_site[k]:
            rv = [EXISTING] + [x for x in rv if not x.startswith("zoning")]
        status.append("Review" if rv else "Pass")
        reasons.append(rv)

    fp = p.iloc[first]
    out = gpd.GeoDataFrame(
        {
            "parcel_id": site_id,
            "screen_status": status,
            "screen_reason": [
                "PASS" if st == "Pass" else "; ".join(dict.fromkeys(rr))
                for st, rr in zip(status, reasons, strict=True)
            ],
            "walk_min_to_hotzone": np.where(np.isfinite(t_site), np.round(t_site, 2), np.nan),
            "brownfield_flag": brownfield,
            "flood_flag": sfha,
            "pipeline_flag": None,
            "slope_pct": np.round(slope, 2),
            "member_parcel_ids": [
                ";".join(pid[members.iloc[k]]) if msize[k] > 1 else None for k in range(ns)
            ],
            "assembled_count": msize,
            "address": fp["address"].to_numpy(),
            "jurisdiction": fp["jurisdiction"].to_numpy(),
            "land_use_class": fp["land_use_class"].to_numpy(),
            "owner_type": fp["owner_type"].to_numpy(),
            "zoning_code": [
                zcode[first[k]]
                if msize[k] == 1
                else ";".join(dict.fromkeys(zcode[members.iloc[k]]))
                for k in range(ns)
            ],
            "zoning_screen": zs_site,
            "lot_sqft": np.round(lot, 0),
            "stalls": stalls,
            "stalls_basis": basis,
            "shape_index": np.round(shape_index, 3),
            "frontage_ft": np.round(front, 0),
            "corner_flag": corner,
            "arterial_flag": arterial,
            "existing_lot_flag": ex_site,
            "zone_a_flag": zone_a,
            "hotzone_id": [zones["zone_id"].iloc[z] if z >= 0 else None for z in zone_site],
            "land_value": land_value,
        },
        geometry=sgeo,
        crs=p.crs,
    )
    ctx.store.write_layer("CandidateParcels", out, "DERIVED")

    st = Counter(status)
    cands = out[out["screen_status"].isin(["Pass", "Review"])]
    in_reach_fail: Counter[str] = Counter()
    for s_, r_, ok in zip(status, reasons, reach_site, strict=True):
        if s_ == "Fail" and ok:
            in_reach_fail.update(list(dict.fromkeys(x.split(":")[0] for x in r_)))
    ex = out[out["existing_lot_flag"].astype(bool)]
    n_c = len(cands)
    lo_n, hi_n = SCOPE_POOL
    top = in_reach_fail.most_common(1)[0][0] if in_reach_fail else "-"
    write_checks(
        ctx,
        "screen",
        [
            Check(
                "QA-E01",
                "CandidateParcels",
                f"Pass + Review candidates within {lo_n}–{hi_n} (SCOPE §5.5)",
                f"{n_c} candidates; filter removing most in-reach sites: {top}",
                n_c,
                f"{lo_n}–{hi_n}",
                lo_n <= n_c <= hi_n,
                severity="warning",
            ),
        ],
    )
    rep = {
        "parcels": n,
        "sites": ns,
        "within_reach_parcels": int(reach.sum()),
        "within_reach_sites": int(reach_site.sum()),
        "paid_market_zones": list(zones["zone_id"]),
        "assemblies": {
            "sites": len(multi),
            "parcels": int(msize[multi].sum()),
            "too_large_fallback": fallback,
            "candidates_assembled": int((cands["assembled_count"] > 1).sum()),
        },
        "status": dict(st),
        "candidates": n_c,
        "candidates_by_status": dict(Counter(cands["screen_status"])),
        "scope_expectation": f"{lo_n}–{hi_n}",
        "in_reach_fail_reasons": in_reach_fail.most_common(),
        "existing_lots": {
            "sites": len(ex),
            "status": dict(Counter(ex["screen_status"])),
            "assembled_and_candidate": int(
                ((ex["assembled_count"] > 1) & ex["screen_status"].isin(["Pass", "Review"])).sum()
            ),
        },
        "zone_a_candidates": int(cands["zone_a_flag"].astype(bool).sum()),
        "not_applied": ["PERMIT (S22 pipeline not configured)"],
        "frontage_measured": "sites within the 8-minute reach only",
    }
    (ctx.run_dir / "screen_report.json").write_text(
        json.dumps(rep, indent=1, default=str), encoding="utf-8"
    )
    return {"sites": ns, "candidates": n_c, "status": dict(st)}


def shed_polygons(
    graph: WalkGraph,
    edges: gpd.GeoDataFrame,
    node_index: pd.Series,
    pts: np.ndarray,
    bands: list[float],
    buffer_crs: float,
) -> list[dict[int, Any]]:
    """Walk-shed polygons per point: edges with both ends reachable within each band (ADR-0027)."""
    u = node_index.reindex(edges["u"].astype(str)).to_numpy()
    v = node_index.reindex(edges["v"].astype(str)).to_numpy()
    ok = ~(np.isnan(u) | np.isnan(v))
    ui, vi = u[ok].astype(int), v[ok].astype(int)
    geo = edges.geometry.to_numpy()[ok]
    node, snap = graph.snap(pts)
    out: list[dict[int, Any]] = []
    for start in range(0, len(pts), BATCH):
        sl = slice(start, start + BATCH)
        dist = csgraph.dijkstra(graph.csr, directed=False, indices=node[sl], limit=max(bands))
        for k, j in enumerate(range(start, min(start + BATCH, len(pts)))):
            d = dist[k] + snap[j]
            res: dict[int, Any] = {}
            for b in sorted(bands):
                sel = (d[ui] <= b) & (d[vi] <= b)
                res[int(b)] = (
                    shapely.union_all(shapely.buffer(geo[sel], buffer_crs)) if sel.any() else None
                )
            out.append(res)
    return out


@register("walksheds", deps=("screen",), reads=("market.demand",), milestone="M5")
def run_walksheds(ctx: RunContext) -> dict[str, Any]:
    """3/5/8-minute network walk-shed polygons for each Pass/Review candidate (ADR-0027)."""
    cfg = ctx.cfg
    c = ctx.store.read_layer("CandidateParcels")
    c = c[c["screen_status"].isin(["Pass", "Review"])].reset_index(drop=True)
    graph = walk_graph(ctx)
    nodes = ctx.store.read_layer("WalkNodes", columns=["node_id"])
    edges = ctx.store.read_layer("WalkEdges", columns=["u", "v"])
    idx = pd.Series(np.arange(len(nodes)), index=nodes["node_id"].astype(str))
    rp = c.geometry.representative_point()
    bands = [float(b) for b in cfg.market.demand.walk_shed_minutes]
    polys = shed_polygons(
        graph,
        edges,
        idx,
        np.c_[rp.x.to_numpy(), rp.y.to_numpy()],
        bands,
        units.m_to_crs(SHED_BUFFER_M, cfg.crs),
    )
    rows = [
        {"parcel_id": pid, "minutes": b, "geometry": g}
        for pid, res in zip(c["parcel_id"], polys, strict=True)
        for b, g in res.items()
        if g is not None
    ]
    if rows:
        out = gpd.GeoDataFrame(rows, geometry="geometry", crs=c.crs)
    else:
        out = gpd.GeoDataFrame({"parcel_id": [], "minutes": []}, geometry=[], crs=c.crs)
    ctx.store.write_layer("WalkSheds", out, "DERIVED")
    return {"candidates": len(c), "sheds": len(out)}
