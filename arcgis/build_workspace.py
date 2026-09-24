"""Build or refresh the local ArcGIS Pro workspace: ``arcgis/ParkIQ_Workspace.aprx``.

A browsing project for looking at everything the pipeline has produced. It is rebuilt from the run
folders, so it never holds state of its own and is not committed (paths are machine-specific).

* one map per run: ``<market> | <run_id>``, layers grouped by SCOPE feature dataset
  (Results, Analysis, Supply, Demand, Cadastral, Reference, Raw), attribute tables (QAQC_Log,
  DataSourceRegistry, ScoreRuns, ParkingRates, …) as standalone tables, rasters (Slope_pct);
  the run's step summaries go into each map's metadata description;
* folder connections to the repo, outputs, docs, configs, markets, scripts and ArcPy scripts;
* a default file geodatabase ``arcgis/ParkIQ_Workspace.gdb`` for your own scratch work.

Run with ArcGIS Pro's Python (close the project in Pro first):

    scripts\\refresh-aprx.ps1                 # latest 2 runs per market
    scripts\\refresh-aprx.ps1 -All            # every run
    <ArcGIS Pro>\\bin\\Python\\envs\\arcgispro-py3\\python.exe arcgis\\build_workspace.py --latest 3

Only this script (in ``arcgis/``) imports arcpy; the library never does.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import arcpy

REPO = Path(__file__).resolve().parents[1]
APRX = REPO / "arcgis" / "ParkIQ_Workspace.aprx"
GDB = REPO / "arcgis" / "ParkIQ_Workspace.gdb"
OUTPUTS = REPO / "outputs"
BLANK = (
    Path(arcpy.GetInstallInfo()["InstallDir"])
    / "Resources"
    / "ArcToolBox"
    / "Services"
    / "routingservices"
    / "data"
    / "Blank.aprx"
)

# Table-of-contents order, top to bottom
GROUPS = ["Results", "Analysis", "Supply", "Demand", "Cadastral", "Reference", "Raw"]
# Layers added but switched off (large or context-only)
OFF_BY_DEFAULT = {"WalkNodes", "Places", "Buildings", "BlockGroups"}
SEP = " | "  # generated map names are "<market> | <run_id>"; other maps are yours and are kept
# Draw order inside Reference (top → bottom); others follow alphabetically
REFERENCE_ORDER = [
    "MarketBoundary",
    "StudyArea",
    "Submarkets",
    "WalkEdges",
    "WalkNodes",
    "HexGrid",
    "FloodHazard",
    "EnvSites",
    "TrafficCounts",
    "Slope_pct",
]


def registry(gpkg: Path) -> list[dict[str, str]]:
    """Rows of the run's ``_ParkIQ_Layers`` registry."""
    con = sqlite3.connect(gpkg)
    try:
        cur = con.execute('SELECT layer, kind, feature_dataset, path FROM "_ParkIQ_Layers"')
        return [
            dict(zip(("layer", "kind", "feature_dataset", "path"), r, strict=True)) for r in cur
        ]
    finally:
        con.close()


def find_runs(latest: int | None, markets: list[str] | None = None) -> list[Path]:
    """Run folders that contain a GeoPackage, newest first per market."""
    runs: list[Path] = []
    for market in sorted(p for p in OUTPUTS.glob("*") if p.is_dir() and not p.name.startswith("_")):
        if markets and market.name not in markets:
            continue
        rs = sorted(
            (r for r in market.iterdir() if r.is_dir() and list(r.glob("ParkIQ_*.gpkg"))),
            reverse=True,
        )
        runs += rs if latest is None else rs[:latest]
    return runs


def open_project() -> arcpy.mp.ArcGISProject:
    """Open the workspace project, creating it from Pro's blank project if needed."""
    if not APRX.exists():
        arcpy.mp.ArcGISProject(str(BLANK)).saveACopy(str(APRX))
        print(f"created {APRX}")
    if not arcpy.Exists(str(GDB)):
        arcpy.management.CreateFileGDB(str(GDB.parent), GDB.name)
    p = arcpy.mp.ArcGISProject(str(APRX))
    for attr, val in (("homeFolder", str(REPO)), ("defaultGeodatabase", str(GDB))):
        try:
            setattr(p, attr, val)
        except (AttributeError, RuntimeError, ValueError) as exc:
            print(f"note: could not set {attr}: {exc}")
    folders = [
        ("ParkIQ repo", REPO),
        ("Run outputs", OUTPUTS),
        ("Docs", REPO / "docs"),
        ("Configs", REPO / "configs"),
        ("Markets", REPO / "markets"),
        ("Scripts", REPO / "scripts"),
        ("ArcGIS scripts", REPO / "arcgis"),
        ("Fixture market (SYNTHETIC)", REPO / "tests" / "fixtures" / "fixture_market"),
    ]
    p.updateFolderConnections(
        [
            {"connectionString": str(path), "alias": alias, "isHomeFolder": path == REPO}
            for alias, path in folders
            if path.exists()
        ],
        validate=False,
    )
    return p


def run_description(run: Path) -> str:
    """Human-readable step summaries from run_log.json for the map metadata."""
    log = run / "run_log.json"
    if not log.exists():
        return ""
    steps = json.loads(log.read_text(encoding="utf-8")).get("steps", {})
    lines = [f"Run folder: {run}"]
    for name, rec in steps.items():
        lines.append(f"{name}: {rec.get('status')} ({rec.get('finished', '')})")
        for k, v in (rec.get("summary") or {}).items():
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)


def add_run(p: arcpy.mp.ArcGISProject, run: Path) -> str:
    """(Re)create the map for one run and return its name."""
    gpkg = next(run.glob("ParkIQ_*.gpkg"))
    market = run.parent.name
    name = f"{market}{SEP}{run.name}"
    m = p.createMap(name, "MAP")
    reg = registry(gpkg)
    feats = [r for r in reg if r["kind"] == "features"]
    tables = sorted(r["layer"] for r in reg if r["kind"] == "attributes")
    rasters = [r for r in reg if r["kind"] == "raster"]

    groups = {}
    for gname in reversed(GROUPS):  # createGroupLayer adds at top, so build bottom-up
        members = [
            r
            for r in feats + rasters
            if (r["feature_dataset"] or "Raw") == gname
            or (gname == "Raw" and r["layer"].startswith("Raw_"))
        ]
        if members:
            groups[gname] = (m.createGroupLayer(gname), members)

    sr_set = False
    for gname, (grp, members) in groups.items():
        order = {n: i for i, n in enumerate(REFERENCE_ORDER)}
        members.sort(key=lambda r: (order.get(r["layer"], 99), r["layer"]))
        for r in members:
            src = str(run / r["path"]) if r["kind"] == "raster" else f"{gpkg}\\main.{r['layer']}"
            try:
                lyr = m.addDataFromPath(src)
            except Exception as exc:  # arcpy raises bare RuntimeError/ValueError
                print(f"  skip {r['layer']}: {exc}")
                continue
            lyr.name = r["layer"]
            m.addLayerToGroup(grp, lyr, "BOTTOM")
            m.removeLayer(lyr)
            if not sr_set and r["layer"] == "MarketBoundary":
                m.spatialReference = arcpy.Describe(src).spatialReference
                sr_set = True
        if gname == "Raw":
            grp.visible = False
    for lyr in m.listLayers():
        if lyr.name in OFF_BY_DEFAULT:
            lyr.visible = False
    for t in tables:
        tbl = m.addDataFromPath(f"{gpkg}\\main.{t}")
        tbl.name = t

    md = arcpy.metadata.Metadata()
    md.title = name
    md.summary = f"ParkIQ run {run.name} ({market})"
    md.description = run_description(run)
    md.tags = f"ParkIQ, {market}"
    m.metadata = md
    return name


def _save(p: arcpy.mp.ArcGISProject) -> int:
    """Save with a short retry (the previous process may still be releasing the file)."""
    for attempt in range(5):
        try:
            p.save()
            return 0
        except OSError as exc:
            if attempt == 4:
                print(
                    f"Could not save {APRX} — is it open in ArcGIS Pro? Close it and re-run. "
                    f"({exc})"
                )
                return 2
            time.sleep(2)
    return 2


def clean() -> int:
    """Child process: create/open the project, set it up, drop generated maps, save."""
    p = open_project()
    for m in list(p.listMaps()):  # generated maps are rebuilt; maps you made yourself are kept
        if SEP in m.name or m.name == "Map":
            p.deleteItem(m)
    return _save(p)


def build_one(run: Path) -> int:
    """Child process: add one run's map to the project and save."""
    p = arcpy.mp.ArcGISProject(str(APRX))
    add_run(p, run)
    return _save(p)


def _child(*args: str) -> int:
    return subprocess.run([sys.executable, __file__, *args], check=False).returncode


def main() -> int:
    """Entry point. The parent never opens the project: ArcGIS Pro's engine can crash when
    several large maps are built in one session, so every change happens in a short-lived child
    process (one to clean, one per run)."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--latest", type=int, default=2, help="runs per market (default 2)")
    ap.add_argument("--all", action="store_true", help="include every run")
    ap.add_argument("--market", action="append", help="only this market slug (repeatable)")
    ap.add_argument("--one", type=Path, help=argparse.SUPPRESS)  # internal: child process
    ap.add_argument("--clean", action="store_true", help=argparse.SUPPRESS)  # internal
    a = ap.parse_args()
    if a.clean:
        return clean()
    if a.one:
        return build_one(a.one)
    runs = find_runs(None if a.all else a.latest, a.market)
    if not runs:
        print(f"No runs found under {OUTPUTS}")
        return 1
    rc = _child("--clean")
    if rc:
        return rc
    for run in runs:
        print(f"map: {run.parent.name}{SEP}{run.name}", flush=True)
        rc = _child("--one", str(run))
        if rc:
            print(f"  failed (exit {rc})")
            return rc
    print(f"saved {APRX} ({len(runs)} run maps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
