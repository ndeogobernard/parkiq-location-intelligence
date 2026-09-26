"""Figures for docs/portfolio reports (run: python docs/portfolio/make_figures.py <run_dir>).

Every map goes through parkiq.maps (map standard, ADR-0076); public figures carry no parcel ids
or owner names.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pyogrio
from matplotlib.patches import Patch

from parkiq.maps import MapSpec, finish, locator, new_map, north_arrow, scale_bar

HERE = Path(__file__).parent
REPO = HERE.parents[1]


def main(run: Path) -> None:
    out = HERE / "figures"
    out.mkdir(exist_ok=True)
    shutil.copyfile(REPO / "docs" / "ERD.png", out / "erd.png")
    g = next(run.glob("ParkIQ_*.gpkg"))
    county = pyogrio.read_dataframe(g, layer="MarketBoundary")
    subs = pyogrio.read_dataframe(g, layer="Submarkets")
    subs["geometry"] = subs.geometry.make_valid()
    core = subs[subs["name"].isin(["Downtown (Zone A/B)", "Arena District"])].union_all()
    view = tuple(core.buffer(2500).bounds)
    p = pyogrio.read_dataframe(g, layer="Parcels", columns=["zoning_status"], bbox=view)
    zones = pyogrio.read_dataframe(g, layer="ParkingZones")
    spec = MapSpec(
        title="One schema, many layers: the zoning screen",
        subtitle="Parcels by zoning-screen result for a commercial surface lot, central Columbus",
        how_to_read=(
            "Each parcel is coloured by what the City code allows for a new paid surface "
            "lot: green allowed, amber needs review, grey not allowed. Outlines show the "
            "Downtown parking zones A/B that change the rule inside Downtown."
        ),
        sources=[
            "Franklin County Auditor parcels (2026-09-23)",
            "City of Columbus zoning and overlays (2026-09)",
            "Zone A/B digitized from City Code §3359.27 Map 2 (Ord. 1532-2013) [VERIFY]",
            "Census TIGER county (2025)",
        ],
        uses_osm=False,
        preliminary=True,
        public=True,
        units="parcel result",
        market_extent=tuple(county.total_bounds),
    )
    fig, ax = new_map(spec)
    colors = {"Pass": "#1a9641", "Review": "#fdae61", "Fail": "#d9d9d9"}
    for k, c in colors.items():
        s = p[p["zoning_status"] == k]
        if len(s):
            s.plot(ax=ax, color=c, lw=0.1, edgecolor="white")
    zones.boundary.plot(ax=ax, color="#333333", lw=1.2)
    ax.set_xlim(view[0], view[2])
    ax.set_ylim(view[1], view[3])
    scale_bar(ax, 2640, "½ mi")
    north_arrow(ax)
    locator(fig, county, view)
    leg = [
        Patch(color=colors["Pass"], label="allowed (by right or conditional)"),
        Patch(color=colors["Review"], label="review (limitation text, overlays, unknown)"),
        Patch(color=colors["Fail"], label="not allowed"),
        Patch(facecolor="none", edgecolor="#333333", label="Downtown parking zones A/B"),
    ]
    finish(fig, ax, leg, "Zoning screen", out / "zoning-screen.png", view=view)
    print("figures written to", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
