"""Step ``supply`` — Phase C supply inventory (SCOPE §5.3; ADR-0020, ADR-0021, ADR-0065).

1. Facilities from OSM parking (S06). OSM on-street types (street_side, lane, …) are dropped:
   on-street supply is S20 metered block faces only (ADR-0021).
2. Adjacent OSM polygons of one facility are dissolved: touching, same type (or type unknown),
   same or missing name and operator.
3. Dedupe (ADR-0020): named pairs within ``dedupe_distance_m`` merge when normalized-name
   similarity ≥ ``dedupe_name_similarity``; an unnamed record merges only with a same-type
   neighbour within ``dedupe_unnamed_touch_m``.
4. Capacity: stated, else surface area × layout efficiency ÷ gross stall area, else garage
   footprint × levels ÷ gross stall area (levels from OSM, else overlapping Overture buildings);
   otherwise unknown (not counted, reported).
5. Private/reserved supply counts at ``private_effective_share``.
6. Off-street and metered on-street stalls are allocated to hexes with the walk-shed decay
   (ADR-0013) → ``Hex_Supply_Daypart`` (same for every daypart until hours are known).
7. Curb sensitivity: potential unmetered local-street curb stalls per hex, flagged when they are
   ≥ ``curb_sensitive_ratio`` × counted effective supply (ADR-0021; carried into M4 hot zones).

The rate surface (IDW per daypart) is not built here: it waits for survey observations (ADR-0023).
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from rapidfuzz import fuzz

from parkiq import units
from parkiq.allocation import WalkGraph, allocate
from parkiq.config import DAYPARTS
from parkiq.qaqc import Check, write_checks
from parkiq.runner import register

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)

TYPE_MAP = {
    "surface": "Surface",
    "multi-storey": "Garage",
    "underground": "Garage",
    "rooftop": "Garage",
    "carports": "Surface",
    "sheds": "Surface",
    "garage_boxes": "Surface",
    "street_side": "OnStreet",
    "lane": "OnStreet",
    "layby": "OnStreet",
    "on_kerb": "OnStreet",
    "half_on_kerb": "OnStreet",
}
PUBLIC_ACCESS = {"yes", "public", "permissive"}
PRIVATE_ACCESS = {
    "private",
    "customers",
    "residents",
    "permit",
    "employees",
    "delivery",
    "no",
    "destination",
    "students",
    "members",
}
TOUCH_TOL_M = 0.15  # "touching" for polygon dissolve — numerical tolerance, not a parameter


def norm_name(v: Any) -> str | None:
    """Lower-case, '&' → 'and', punctuation to spaces; None for blank."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    s = re.sub(r"[^a-z0-9 ]+", " ", str(v).lower().replace("&", " and "))
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _missing(v: Any) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA or v == ""


def similarity(a: str | None, b: str | None) -> float:
    """Token-set similarity 0–1 of two normalized names (0 if either is missing).

    Names whose numbers differ ("lot 5" vs "lot 6") are different facilities: similarity 0.
    """
    if _missing(a) or _missing(b):
        return 0.0
    na, nb = re.findall(r"\d+", str(a)), re.findall(r"\d+", str(b))
    if (na or nb) and sorted(na) != sorted(nb):
        return 0.0
    return float(fuzz.token_set_ratio(str(a), str(b))) / 100.0


class _UF:
    """Union-find over record indices with per-component attribute sets."""

    def __init__(self, n: int, names: list[str | None], ops: list[str | None], types: list[str]):
        self.p = list(range(n))
        self.names = [set() if _missing(x) else {x} for x in names]
        self.ops = [set() if _missing(x) else {x} for x in ops]
        self.types = [{t} if t != "Unknown" else set() for t in types]

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        self.p[rb] = ra
        self.names[ra] |= self.names[rb]
        self.ops[ra] |= self.ops[rb]
        self.types[ra] |= self.types[rb]

    def compatible_types(self, a: int, b: int) -> bool:
        ta, tb = self.types[self.find(a)], self.types[self.find(b)]
        return not ta or not tb or ta == tb


def osm_facilities(osm: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    """OSM parking features → candidate facility records (on-street types removed)."""
    f = osm.copy()
    f["ptype"] = f["parking"].map(TYPE_MAP).fillna("Unknown")
    stats = {"osm_features": len(f), "osm_onstreet_dropped": int((f["ptype"] == "OnStreet").sum())}
    f = f[f["ptype"] != "OnStreet"].copy()
    f["nname"] = f["name"].map(norm_name)
    f["nop"] = f["operator"].map(norm_name)
    f["source_ids"] = f["osm_id"].astype(str)
    return f.reset_index(drop=True), stats


def dissolve_adjacent(f: gpd.GeoDataFrame, crs: Any) -> gpd.GeoDataFrame:
    """Merge touching polygons of the same facility (same type/name/operator or missing)."""
    poly = f[f.geom_type.isin(["Polygon", "MultiPolygon"])]
    tol = units.m_to_crs(TOUCH_TOL_M, crs)
    left = gpd.GeoDataFrame(geometry=poly.geometry.buffer(tol), crs=f.crs)
    pairs = gpd.sjoin(left, poly[["geometry"]], predicate="intersects")
    pairs = pairs[pairs.index < pairs["index_right"]]
    uf = _UF(len(f), list(f["nname"]), list(f["nop"]), list(f["ptype"]))
    for a, b in zip(pairs.index, pairs["index_right"], strict=True):
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb or not uf.compatible_types(a, b):
            continue
        if len(uf.names[ra] | uf.names[rb]) > 1 or len(uf.ops[ra] | uf.ops[rb]) > 1:
            continue
        uf.union(a, b)
    return _merge(f, np.array([uf.find(i) for i in range(len(f))]))


def dedupe(
    f: gpd.GeoDataFrame, crs: Any, dist_m: float, touch_m: float, threshold: float
) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    """ADR-0020 merge rules across all facility records."""
    d = units.m_to_crs(dist_m, crs)
    t = units.m_to_crs(touch_m, crs)
    left = gpd.GeoDataFrame(geometry=f.geometry.buffer(d), crs=f.crs)
    pairs = gpd.sjoin(left, f[["geometry"]], predicate="intersects")
    pairs = pairs[pairs.index < pairs["index_right"]]
    uf = _UF(len(f), list(f["nname"]), list(f["nop"]), list(f["ptype"]))
    geoms = f.geometry.to_numpy()
    n_named = n_unnamed = 0
    for a, b in zip(pairs.index, pairs["index_right"], strict=True):
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            continue
        gap = float(shapely.distance(geoms[a], geoms[b]))
        na, nb = uf.names[ra], uf.names[rb]
        if na and nb:
            best = max(similarity(x, y) for x in na for y in nb)
            if gap <= d and best >= threshold:
                uf.union(a, b)
                n_named += 1
        elif gap <= t and uf.compatible_types(a, b):
            uf.union(a, b)
            n_unnamed += 1
    out = _merge(f, np.array([uf.find(i) for i in range(len(f))]))
    return out, {"merged_named_pairs": n_named, "merged_unnamed_pairs": n_unnamed}


def _first(s: pd.Series) -> Any:
    v = s.dropna()
    return v.iloc[0] if len(v) else None


def _merge(f: gpd.GeoDataFrame, comp: np.ndarray) -> gpd.GeoDataFrame:
    """Collapse records by component label."""
    f = f.assign(_c=comp)
    rows = []
    for _c, g in f.groupby("_c", sort=True):
        polys = g[g.geom_type.isin(["Polygon", "MultiPolygon"])]
        geom = polys.geometry.union_all() if len(polys) else g.geometry.iloc[0]
        types = [t for t in g["ptype"] if t != "Unknown"]
        cap = pd.to_numeric(g["capacity"], errors="coerce")
        stated = (
            float(cap.sum())
            if len(g) and cap.notna().all()
            else (float(cap.max()) if cap.notna().any() and len(polys) <= 1 else np.nan)
        )
        access = g["access"].dropna().astype(str).str.lower()
        rows.append(
            {
                "name": _first(g["name"]),
                "nname": _first(g["nname"]),
                "operator": _first(g["operator"]),
                "nop": _first(g["nop"]),
                "ptype": max(set(types), key=types.count) if types else "Unknown",
                "parking": _first(g["parking"]),
                "capacity": stated,
                "fee": "yes" if (g["fee"] == "yes").any() else _first(g["fee"]),
                "access": (
                    next((a for a in access if a in PUBLIC_ACCESS), None)
                    or (access.iloc[0] if len(access) else None)
                ),
                "levels": pd.to_numeric(g["levels"], errors="coerce").max(),
                "parts": int(g["parts"].sum()) if "parts" in g else len(g),
                "source_ids": ";".join(sorted(";".join(g["source_ids"]).split(";"))),
                "geometry": geom,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=f.crs).reset_index(drop=True)


def capacity(
    f: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame | None,
    stall_sqft: float,
    efficiency: float,
    crs: Any,
    surface_factor: float = 1.0,
) -> gpd.GeoDataFrame:
    """Stated / estimated capacity and its source for each facility.

    Surface area estimates are multiplied by ``surface_factor`` (ADR-0067: calibrated to stated
    capacities of existing lots); ``capacity_est_raw`` keeps the uncalibrated estimate.
    """
    f = f.copy()
    f["capacity"] = pd.to_numeric(f["capacity"], errors="coerce")
    f["levels"] = pd.to_numeric(f["levels"], errors="coerce")
    is_poly = f.geom_type.isin(["Polygon", "MultiPolygon"])
    f["area_sqft"] = np.where(
        is_poly, f.geometry.area.map(lambda a: units.crs_area_to_sqft(a, crs)), np.nan
    )
    levels = f["levels"].copy()
    garage = (f["ptype"] == "Garage") & is_poly
    if buildings is not None and len(buildings) and garage.any():
        g = f.loc[garage, ["geometry"]]
        inter = gpd.overlay(
            g.reset_index(names="fid"),
            buildings[["levels", "geometry"]],
            how="intersection",
            keep_geom_type=True,
        )
        inter["share"] = inter.area / f.geometry.area.reindex(inter["fid"]).to_numpy()
        lv = inter[inter["share"] >= 0.5].groupby("fid")["levels"].max()
        levels = levels.fillna(lv.reindex(f.index))
    est = np.full(len(f), np.nan)
    surf = is_poly & (f["ptype"] != "Garage")
    est[surf.to_numpy()] = (f.loc[surf, "area_sqft"] * efficiency / stall_sqft).to_numpy()
    raw = est.copy()
    est[surf.to_numpy()] *= surface_factor
    gl = garage & levels.notna()
    est[gl.to_numpy()] = (f.loc[gl, "area_sqft"] * levels[gl] / stall_sqft).to_numpy()
    f["levels"] = levels
    f["capacity_est"] = np.round(est, 0)
    f["capacity_est_raw"] = np.round(raw, 0)
    f["capacity_stated"] = f["capacity"]
    src = pd.Series(None, index=f.index, dtype="object")
    src[surf] = "area" if surface_factor == 1.0 else "area x factor"
    src[gl] = "footprint x levels"
    src[f["capacity_stated"].notna()] = "stated"
    f["capacity_source"] = src
    f["capacity_final"] = f["capacity_stated"].fillna(f["capacity_est"])
    return f


def apply_exclusions(
    f: gpd.GeoDataFrame, rules: pd.DataFrame, parcels: gpd.GeoDataFrame | None
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Drop non-parking lots matching a reviewable rule list (pattern, field, reason).

    ``field`` is a facility column (``name``, ``operator``) or ``parcel_land_use_code`` (the
    land-use code of the parcel under the facility's representative point). Returns
    (kept, excluded with ``exclusion_reason``).
    """
    f = f.copy()
    if parcels is not None and (rules["field"] == "parcel_land_use_code").any():
        pts = gpd.GeoDataFrame(geometry=f.geometry.representative_point(), crs=f.crs)
        j = gpd.sjoin(pts, parcels[["land_use_code", "geometry"]], predicate="within")
        f["parcel_land_use_code"] = j[~j.index.duplicated()]["land_use_code"].reindex(f.index)
    reason = pd.Series(None, index=f.index, dtype="object")
    for r in rules.itertuples(index=False):
        if r.field not in f.columns:
            continue
        col = f[r.field]
        hit = col.notna() & col.astype(str).str.contains(r.pattern, case=False, regex=True)
        reason[hit & reason.isna()] = r.reason
    excluded = f[reason.notna()].assign(exclusion_reason=reason[reason.notna()])
    kept = f[reason.isna()].drop(columns=["parcel_land_use_code"], errors="ignore")
    return kept.reset_index(drop=True), excluded.reset_index(drop=True)


def _cover(a: gpd.GeoDataFrame, b: gpd.GeoDataFrame) -> pd.Series:
    """Area of each polygon in ``a`` covered by polygons of ``b`` (index-aligned to ``a``)."""
    a = a.reset_index(drop=True)
    b = b.reset_index(drop=True)
    j = gpd.sjoin(a[["geometry"]], b[["geometry"]], predicate="intersects")
    if j.empty:
        return pd.Series(0.0, index=a.index)
    ia = shapely.area(
        shapely.intersection(
            a.geometry.values[j.index.to_numpy()], b.geometry.values[j["index_right"].to_numpy()]
        )
    )
    return pd.Series(ia, index=j.index).groupby(level=0).sum().reindex(a.index).fillna(0.0)


def parcel_estimate(
    parcels: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    osm_polys: gpd.GeoDataFrame,
    classes: list[str],
    max_acres: float,
    crs: Any,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """Estimate surface parking on parcels OSM does not map (ADR-0074).

    For each land-use class, the share of a parcel's open area (lot − building footprint) that OSM
    maps as parking is measured on parcels ≤ ``max_acres`` that DO carry an OSM lot (median per
    parcel); the share is applied to same-class parcels ≤ ``max_acres`` with no OSM parking at all.
    Returns estimated lot records (``area_sqft`` = estimated parking area) and calibration stats.
    """
    p = parcels[parcels["land_use_class"].isin(classes)].copy().reset_index(drop=True)
    p = p[~p["excluded_use_flag"].fillna(False).astype(bool)].reset_index(drop=True)
    area = p.geometry.area
    p["acres"] = area.map(lambda a: units.crs_area_to_sqft(a, crs)) / 43560.0
    p = p[p["acres"] <= max_acres].reset_index(drop=True)
    area = p.geometry.area
    open_area = (area - _cover(p, buildings)).clip(lower=0)
    osm_area = _cover(p, osm_polys)
    covered = osm_area > 0
    share = (osm_area / open_area.replace(0, np.nan))[covered].clip(upper=1)
    by_class = share.groupby(p.loc[covered, "land_use_class"]).median()
    stats = {
        "calibration_parcels": {
            c: int((p.loc[covered, "land_use_class"] == c).sum()) for c in classes
        },
        "share_median": {k: float(v) for k, v in by_class.items()},
    }
    u = p[~covered].copy()
    u["est_area"] = open_area[~covered] * u["land_use_class"].map(by_class)
    u = u[u["est_area"].fillna(0) > 0]
    est_sqft = u["est_area"].map(lambda a: units.crs_area_to_sqft(a, crs))
    out = gpd.GeoDataFrame(
        {
            "name": None,
            "nname": None,
            "operator": None,
            "nop": None,
            "ptype": "Surface",
            "parking": "surface (parcel estimate)",
            "capacity": np.nan,
            "fee": None,
            "access": None,
            "levels": np.nan,
            "parts": 1,
            "source_ids": "parcel:" + u["parcel_id"].astype(str),
            "land_use_code": u["land_use_code"],
            "est_area_sqft": est_sqft.to_numpy(),
        },
        geometry=u.geometry.representative_point().to_numpy(),
        crs=u.crs,
    )
    stats["parcels_estimated"] = len(out)
    return out.reset_index(drop=True), stats


def private_flags(f: gpd.GeoDataFrame, unknown_private: bool) -> pd.Series:
    """True = private/reserved (counted at the effective share)."""
    acc = f["access"].fillna("").astype(str).str.lower()
    fee = f["fee"].fillna("").astype(str).str.lower()
    public = acc.isin(PUBLIC_ACCESS) | (fee == "yes")
    private = acc.isin(PRIVATE_ACCESS)
    return pd.Series(
        np.where(public, False, np.where(private, True, unknown_private)), index=f.index
    )


def curb_by_hex(
    edges: gpd.GeoDataFrame,
    metered: gpd.GeoDataFrame,
    hexes: gpd.GeoDataFrame,
    highways: list[str],
    crs: Any,
) -> pd.Series:
    """Unmetered local-street curb (ft, both sides) per hex_id, by edge midpoint."""
    hw = edges["highway"].astype(str)
    local = edges[hw.apply(lambda h: any(x in h for x in highways))].copy()
    key = [tuple(sorted((str(a), str(b)))) for a, b in zip(local["u"], local["v"], strict=True)]
    local = local.assign(_k=key).drop_duplicates("_k")
    if len(metered):
        near = gpd.sjoin(
            local[["geometry"]],
            gpd.GeoDataFrame(geometry=metered.geometry.buffer(units.m_to_crs(12.0, crs)), crs=crs),
            predicate="intersects",
        ).index.unique()
        local = local.drop(index=near)
    mid = gpd.GeoDataFrame(
        {"ft": local["length_m"].to_numpy() / 0.3048 * 2.0},
        geometry=local.geometry.interpolate(0.5, normalized=True),
        crs=crs,
    )
    j = gpd.sjoin(mid, hexes[["hex_id", "geometry"]], predicate="within")
    return j.groupby("hex_id")["ft"].sum()


@register(
    "supply",
    deps=("qaqc",),
    reads=(
        "market.supply",
        "market.site",
        "market.demand.walk_shed_minutes",
        "market.demand.decay_weights",
        "market.network",
    ),
    milestone="M3",
)
def run_supply(ctx: RunContext) -> dict[str, Any]:
    """Phase C supply inventory, capacity, allocation and curb sensitivity."""
    cfg = ctx.cfg
    sc, site, dm = cfg.market.supply, cfg.market.site, cfg.market.demand
    crs = cfg.crs
    written = set(ctx.store.written_layers())
    osm = ctx.store.read_layer("ParkingOSM")
    f0, st = osm_facilities(osm)
    subs = ctx.store.read_layer("Submarkets") if "Submarkets" in written else None
    downtown = (
        ctx.store.read_layer("ParkingZones").union_all() if "ParkingZones" in written else None
    )

    def area_counts(g: gpd.GeoDataFrame, cap: str | None = None) -> dict[str, float]:
        if downtown is None:
            return {}
        inside = g.geometry.intersects(downtown)
        out: dict[str, float] = {"records": int(inside.sum())}
        if cap:
            out["stalls"] = float(g.loc[inside, cap].fillna(0).sum())
        return out

    f0["parts"] = 1
    f1 = dissolve_adjacent(f0, crs)
    f2, dd = dedupe(
        f1,
        crs,
        sc.dedupe_distance_m,
        float(sc.dedupe_unnamed_touch_m or 0),
        float(sc.dedupe_name_similarity or 1),
    )
    bld = ctx.store.read_layer("Buildings") if "Buildings" in written else None
    stall, eff = site.stall_area_sqft_gross, site.layout_efficiency
    factor = float(sc.surface_capacity_factor or 1.0)  # existing lots only (ADR-0067)
    counts = {}
    for label, g in (("osm_records", f0), ("after_dissolve", f1), ("after_dedupe", f2)):
        gc = capacity(g, bld, stall, eff, crs, factor)
        counts[label] = {
            "records": len(gc),
            "stalls": float(gc["capacity_final"].fillna(0).sum()),
            "downtown": area_counts(gc, "capacity_final"),
        }
    excl_report: dict[str, Any] = {}
    if sc.exclusions_path is not None:
        rules = pd.read_csv(sc.exclusions_path, dtype=str)
        parcels = ctx.store.read_layer("Parcels", columns=["land_use_code"])
        f2, excluded = apply_exclusions(f2, rules, parcels)
        ex = capacity(excluded, bld, stall, eff, crs, factor)
        top = ex.sort_values("capacity_final", ascending=False).head(10)
        excl_report = {
            "facilities": len(ex),
            "stalls": float(ex["capacity_final"].fillna(0).sum()),
            "by_reason": {
                str(k): {"facilities": len(v), "stalls": float(v["capacity_final"].fillna(0).sum())}
                for k, v in ex.groupby("exclusion_reason")
            },
            "largest": top[["name", "operator", "exclusion_reason", "capacity_final"]].to_dict(
                "records"
            ),
        }
    fac = capacity(f2, bld, stall, eff, crs, factor)
    fac["private_flag"] = private_flags(fac, bool(sc.unknown_access_as_private))
    est_report: dict[str, Any] = {}
    if sc.parcel_estimate_classes and sc.parcel_estimate_max_acres:
        parc = ctx.store.read_layer(
            "Parcels", columns=["parcel_id", "land_use_class", "land_use_code", "excluded_use_flag"]
        )
        polys = osm[osm.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        polys["geometry"] = polys.geometry.make_valid()
        bpoly = bld if bld is not None else gpd.GeoDataFrame(geometry=[], crs=crs)
        est, est_report = parcel_estimate(
            parc,
            bpoly,
            polys,
            list(sc.parcel_estimate_classes),
            float(sc.parcel_estimate_max_acres),
            crs,
        )
        if sc.exclusions_path is not None and len(est):
            rules = pd.read_csv(sc.exclusions_path, dtype=str)
            est = est.assign(parcel_land_use_code=est["land_use_code"])
            est, ex2 = apply_exclusions(est, rules[rules["field"] == "parcel_land_use_code"], None)
            est_report["excluded_by_list"] = len(ex2)
        est["capacity_stated"] = np.nan
        est["capacity_est"] = np.round(est["est_area_sqft"] * eff / stall * factor, 0)
        est["capacity_est_raw"] = np.round(est["est_area_sqft"] * eff / stall, 0)
        est["capacity_final"] = est["capacity_est"]
        est["capacity_source"] = "parcel estimate"
        est["area_sqft"] = est["est_area_sqft"]
        est["private_flag"] = True
        est_report["stalls"] = float(est["capacity_final"].sum())
        fac = gpd.GeoDataFrame(
            pd.concat(
                [fac, est.drop(columns=["est_area_sqft", "land_use_code"])], ignore_index=True
            ),
            crs=crs,
        )
    fac["type"] = fac["ptype"].replace({"Unknown": "Surface"})
    fac["facility_id"] = [f"F{i:06d}" for i in range(1, len(fac) + 1)]
    fac["fee_flag"] = fac["fee"].map({"yes": True, "no": False})
    pts = fac.copy()
    pts["geometry"] = fac.geometry.representative_point()
    pts = gpd.GeoDataFrame(pts, geometry="geometry", crs=crs)
    if subs is not None and len(subs):
        j = gpd.sjoin(pts[["geometry"]], subs[["name", "geometry"]], predicate="within")
        pts["submarket"] = j[~j.index.duplicated()]["name"].reindex(pts.index)
    else:
        pts["submarket"] = None
    out = pts[
        [
            "facility_id",
            "name",
            "type",
            "capacity_stated",
            "capacity_est",
            "capacity_source",
            "area_sqft",
            "fee_flag",
            "private_flag",
            "operator",
            "access",
            "parts",
            "source_ids",
            "submarket",
            "geometry",
        ]
    ].copy()
    for c in ("rate_hour", "rate_day", "rate_month", "rate_event"):
        out[c] = None  # survey observations (ADR-0023) — rate surface waits for round 1
    out = gpd.GeoDataFrame(out, geometry="geometry", crs=crs)
    ctx.store.write_layer("SupplyFacilities", out, "S06")

    # ---- allocation to hexes
    hexes = ctx.store.read_layer("HexGrid")
    graph = WalkGraph.from_layers(
        ctx.store.read_layer("WalkNodes"),
        ctx.store.read_layer("WalkEdges"),
        crs,
        cfg.market.network.walking_speed_m_s,
    )
    cap = fac["capacity_final"].fillna(0).to_numpy()
    effective = np.where(fac["private_flag"], cap * sc.private_effective_share, cap)
    bands = [float(b) for b in dm.walk_shed_minutes]
    weights = {float(k): float(v) for k, v in dm.decay_weights.items()}
    off_raw, s1 = allocate(pts, cap, hexes, graph, bands, weights)
    off_eff, _ = allocate(pts, effective, hexes, graph, bands, weights)
    ons = ctx.store.read_layer("OnStreetSegments") if "OnStreetSegments" in written else None
    if ons is not None and len(ons):
        mid = gpd.GeoDataFrame(geometry=ons.geometry.interpolate(0.5, normalized=True), crs=crs)
        on_alloc, s2 = allocate(
            mid, ons["stalls_est"].fillna(0).to_numpy(), hexes, graph, bands, weights
        )
        metered = ons
    else:
        on_alloc, s2 = pd.Series(0.0, index=off_raw.index), {}
        metered = gpd.GeoDataFrame(geometry=[], crs=crs)
    curb_ft = (
        curb_by_hex(
            ctx.store.read_layer("WalkEdges"), metered, hexes, list(sc.curb_local_highways), crs
        )
        .reindex(off_raw.index)
        .fillna(0.0)
    )
    pot = curb_ft / sc.onstreet_stall_length_ft
    eff_total = off_eff + on_alloc
    ratio = float(sc.curb_sensitive_ratio or np.inf)
    flag = (pot > 0) & (pot >= ratio * eff_total)
    base = pd.DataFrame(
        {
            "hex_id": off_raw.index,
            "supply_stalls": (off_raw + on_alloc).to_numpy(),
            "effective_supply_stalls": eff_total.to_numpy(),
            "offstreet_stalls": off_raw.to_numpy(),
            "onstreet_stalls": on_alloc.to_numpy(),
            "unmetered_curb_ft": curb_ft.to_numpy(),
            "potential_curb_stalls": pot.to_numpy(),
            "curb_sensitive_flag": flag.to_numpy(),
        }
    )
    table = pd.concat([base.assign(daypart=dp) for dp in DAYPARTS], ignore_index=True)
    ctx.store.write_table("Hex_Supply_Daypart", table)

    # ---- QA
    both = fac[
        fac["capacity_stated"].notna() & fac["capacity_est"].notna() & (fac["capacity_stated"] > 0)
    ]
    err = (both["capacity_est"] - both["capacity_stated"]).abs() / both["capacity_stated"]
    sb = fac[
        (fac["type"] == "Surface") & fac["capacity_stated"].gt(0) & fac["capacity_est_raw"].gt(0)
    ]
    ratio_now = sb["capacity_stated"] / sb["capacity_est_raw"]
    factor_check = {
        "configured": factor,
        "n": len(sb),
        "median_now": float(ratio_now.median()) if len(sb) else None,
        "iqr_now": [float(x) for x in ratio_now.quantile([0.25, 0.75])] if len(sb) else None,
    }
    med = float(err.median()) if len(err) else float("nan")
    total_in = float(cap.sum() + (ons["stalls_est"].fillna(0).sum() if ons is not None else 0))
    total_out = float((off_raw + on_alloc).sum())
    checks = [
        Check(
            "QA-C01",
            "SupplyFacilities",
            "capacity: median |estimated − stated| / stated",
            f"{med:.1%} over {len(both)} facilities with both",
            med,
            "<= 20%",
            bool(len(err)) and med <= 0.20,
            severity="warning",
        ),
        Check(
            "QA-C02",
            "Hex_Supply_Daypart",
            "allocation conserves stalls (outside grid dropped)",
            f"{total_out:,.0f} of {total_in:,.0f}",
            total_out / total_in if total_in else 1,
            ">= 99%",
            total_in == 0 or total_out / total_in >= 0.99,
            severity="warning",
        ),
        Check(
            "QA-C03",
            "SupplyFacilities",
            "facilities without capacity (not counted)",
            str(int(fac["capacity_final"].isna().sum())),
            int(fac["capacity_final"].isna().sum()),
            "reported",
            True,
            severity="info",
        ),
    ]
    write_checks(ctx, "supply", checks)

    def by(col: str) -> dict[str, Any]:
        g = fac.assign(
            k=pts[col].fillna("(outside survey areas)") if col == "submarket" else fac[col]
        )
        return {
            k: {
                "facilities": len(v),
                "stalls": float(v["capacity_final"].fillna(0).sum()),
                "private": int(v["private_flag"].sum()),
                "no_capacity": int(v["capacity_final"].isna().sum()),
            }
            for k, v in g.groupby("k")
        }

    report = {
        **st,
        "dedupe": dd,
        "counts": counts,
        "by_type": by("type"),
        "by_submarket": by("submarket"),
        "capacity_source": fac["capacity_source"].fillna("none").value_counts().to_dict(),
        "surface_capacity_factor": factor_check,
        "parcel_estimate": est_report,
        "exclusions": excl_report,
        "capacity_qa": {
            "n_both": len(both),
            "median_abs_pct_err": med,
            "share_within_20pct": float((err <= 0.2).mean()) if len(err) else None,
        },
        "onstreet": {
            "block_faces": 0 if ons is None else len(ons),
            "stalls": 0.0 if ons is None else float(ons["stalls_est"].fillna(0).sum()),
        },
        "allocation": {"offstreet": s1, "onstreet": s2, "in": total_in, "out": total_out},
        "curb_sensitive_hexes": int(flag.sum()),
    }
    (ctx.run_dir / "supply_report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8"
    )
    return {
        "facilities": len(fac),
        "stalls": float(cap.sum()),
        "curb_sensitive_hexes": int(flag.sum()),
    }
