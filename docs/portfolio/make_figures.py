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
        title="Where the zoning code allows a paid parking lot",
        subtitle="Parcels by zoning-screen result for a commercial surface lot, central Columbus",
        how_to_read=(
            "Each parcel is coloured by what the City code allows for a new paid surface "
            "lot: green allowed, amber needs review, grey not allowed. Outlines show the "
            "Downtown parking zones A/B that change the rule inside Downtown."
        ),
        sources=[
            "Franklin County Auditor parcels (2026-09-23)",
            "City of Columbus zoning and overlays (2026-09)",
            "Zone A/B digitized from City Code §3359.27 Map 2 "
            "(Ord. 1532-2013; unofficial digitization)",
            "Census TIGER county (2025)",
        ],
        uses_osm=False,
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


def pipeline_figure(run: Path, out: Path) -> None:
    """Report 3 figure: the pipeline steps with what each produced in the run (not a map)."""
    import json

    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    def rep(name: str) -> dict:  # type: ignore[type-arg]
        f = run / name
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    scr, gap = rep("screen_report.json"), rep("gap_report.json")
    import sqlite3

    gpkg = next(run.glob("ParkIQ_*.gpkg"))
    with sqlite3.connect(gpkg) as con:
        anchors = con.execute('SELECT COUNT(*) FROM "DemandAnchors"').fetchone()[0]
    nl = chr(10)
    zones = gap.get("screening", {}).get("zones", 0)
    steps = [
        (f"schema +{nl}setup", f"GeoPackage, H3 grid,{nl}walking network, slope"),
        (f"ingest +{nl}qaqc", f"public sources,{nl}QA log"),
        ("demand", f"{anchors:,} anchors,{nl}5 times of week"),
        ("supply", f"lots, garages,{nl}metered curb"),
        ("gap", f"{zones} paid-parking{nl}hot zones"),
        (
            "screen",
            f"{scr.get('parcels', 0):,} parcels{nl}to {scr.get('candidates', 0)} candidates",
        ),
        (f"walk sheds +{nl}criteria", f"3/5/8-min sheds,{nl}10 criteria"),
        (f"scoring +{nl}sensitivity", f"3 scenarios,{nl}1,000 weightings"),
        (f"finance,{nl}shortlist, package", f"next: buy and{nl}ground lease"),
    ]
    fig, ax = plt.subplots(figsize=(16, 5.2), dpi=100)
    ax.set_axis_off()
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 5.2)
    w, gapx = 1.55, 0.2
    for i, (name, what) in enumerate(steps):
        x = 0.15 + i * (w + gapx)
        done = i < len(steps) - 1
        c = "#2c7fb8" if done else "#999999"
        ax.add_patch(
            FancyBboxPatch(
                (x, 1.4),
                w,
                2.4,
                boxstyle="round,pad=0.04",
                fc=c,
                alpha=0.12 if done else 0.08,
                ec=c,
                lw=1.6,
            )
        )
        ax.text(
            x + w / 2,
            3.45,
            name,
            ha="center",
            va="top",
            fontsize=10,
            fontweight="bold",
            color=c,
            wrap=True,
        )
        ax.text(x + w / 2, 2.55, what, ha="center", va="top", fontsize=9)
        if i:
            ax.add_patch(
                FancyArrowPatch(
                    (x - gapx, 2.6), (x, 2.6), arrowstyle="-|>", mutation_scale=12, color="#555"
                )
            )
    ax.text(
        0.15,
        4.6,
        "The ParkIQ pipeline: each step reads the previous steps' layers from one GeoPackage",
        fontsize=15,
        fontweight="bold",
    )
    ax.text(
        0.15,
        0.7,
        "Franklin County run, September 2026. Grey: waits for partner finance inputs. "
        "Each step also runs as an ArcGIS Pro tool.",
        fontsize=9.5,
        color="#444",
    )
    fig.savefig(out / "pipeline-steps.png", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
    pipeline_figure(Path(sys.argv[1]), HERE / "figures")
