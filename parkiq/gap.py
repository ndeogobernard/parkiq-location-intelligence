"""Step ``gap`` — Phase D gap analysis and hot zones (SCOPE §5.4; ADR-0024, ADR-0071).

``gap_stalls = demand − effective supply`` and ``gap_ratio = demand / supply`` per hex and daypart
(``rate_index`` stays null until the rate surface exists — ADR-0023). A hex qualifies for a hot zone
when its weekday-day gap is positive and its gap is also positive in at least one evening or event
daypart (wd_eve, we_eve, event). Qualifying hexes that share an edge (H3 k = 1) form one zone.

Flags per zone (ADR-0071): ``zone_size`` / ``single_hex_flag``; ``single_anchor_flag`` when one
anchor contributes more than ``demand.single_anchor_share`` of the zone's positive weekday-day gap
(so one large employer — whose own lots count at the private share — cannot create a hot zone on
its own); ``curb_sensitive_*`` from the supply step; ``jurisdictions`` touched (for the zoning-table
decision).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

from parkiq.config import DAYPARTS
from parkiq.qaqc import Check, write_checks
from parkiq.runner import register

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)
SECOND = ("wd_eve", "we_eve", "event")


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


@register(
    "gap", deps=("demand", "supply"), reads=("market.demand", "market.supply"), milestone="M4"
)
def run_gap(ctx: RunContext) -> dict[str, Any]:
    """Gap per hex/daypart and hot zones."""
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
    g["rate_index"] = None
    ctx.store.write_table(
        "Hex_Gap_Daypart", g[["hex_id", "daypart", "gap_stalls", "gap_ratio", "rate_index"]]
    )
    wide = g.pivot_table(index="hex_id", columns="daypart", values="gap_stalls", aggfunc="sum")
    wide = wide.reindex(columns=list(DAYPARTS)).fillna(0.0)
    qual = wide[(wide["wd_day"] > 0) & (wide[list(SECOND)] > 0).any(axis=1)]
    comps = components(list(qual.index))

    hexes = ctx.store.read_layer("HexGrid").set_index("hex_id")
    curb = s[s["daypart"] == "wd_day"].set_index("hex_id")["curb_sensitive_flag"].fillna(0)
    wpath = ctx.run_dir / "demand_weights.parquet"
    weights = pd.read_parquet(wpath) if wpath.exists() else None
    anchors = ctx.store.read_layer("DemandAnchors", columns=["anchor_id", "demand_wd_day"])
    dwd = dict(zip(anchors["anchor_id"], anchors["demand_wd_day"], strict=True))
    places = None
    if dm.workplace_places_path is not None:
        places = gpd.read_file(dm.workplace_places_path).to_crs(ctx.cfg.crs)[["NAME", "geometry"]]
    share_max = float(dm.single_anchor_share or 1.0)
    min_lot = float(ctx.cfg.market.site.target_stalls_range[0])
    rows = []
    for i, comp in enumerate(comps, start=1):
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
        rows.append({
            "zone_id": f"HZ{i:04d}",
            "dayparts_positive": ";".join(dp for dp in DAYPARTS if (pos[dp] > 0).any()),
            "total_gap_stalls": gap_pos,
            "mean_rate_index": None,
            "zone_size": len(comp),
            "single_hex_flag": len(comp) == 1,
            "top_anchor_id": top_id,
            "top_anchor_share": top_share,
            "single_anchor_flag": top_share > share_max,
            "curb_sensitive_hexes": ncurb,
            "curb_sensitive_flag": ncurb > 0,
            "jurisdictions": jur or "(unincorporated)",
            "below_min_lot_flag": gap_pos < min_lot,
            "geometry": geom,
        })  # fmt: skip
    hz = gpd.GeoDataFrame(rows, geometry="geometry", crs=ctx.cfg.crs) if rows else None
    if hz is not None:
        ctx.store.write_layer("HotZones", hz, "DERIVED")
    n = 0 if hz is None else len(hz)
    write_checks(ctx, "gap", [
        Check("QA-G01", "HotZones", "hot zones found", str(n), n, "> 0 (reported)", n > 0,
              severity="warning"),
    ])  # fmt: skip
    rep = {
        "hexes_qualifying": len(qual),
        "zones": n,
        "single_hex_zones": 0 if hz is None else int(hz["single_hex_flag"].sum()),
        "single_anchor_zones": 0 if hz is None else int(hz["single_anchor_flag"].sum()),
        "curb_sensitive_zones": 0 if hz is None else int(hz["curb_sensitive_flag"].sum()),
        "below_min_lot_zones": 0 if hz is None else int(hz["below_min_lot_flag"].sum()),
        "positive_gap_hexes": {dp: int((wide[dp] > 0).sum()) for dp in DAYPARTS},
    }
    (ctx.run_dir / "gap_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
