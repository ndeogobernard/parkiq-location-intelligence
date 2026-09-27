"""Export a run GeoPackage to a file geodatabase with domains, subtypes and relationship classes.

Runs in ArcGIS Pro's Python (arcpy). Called by ``parkiq export-gdb`` (ADR-0045), or directly:

    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" arcgis/export_gdb.py
        --gpkg <run>/ParkIQ_<slug>.gpkg --schema schema/schema.yaml --out <run>/ParkIQ_<slug>.gdb

* Feature classes go into their feature datasets (schema ``feature_dataset``) in the analysis CRS;
  WGS 84 layers (raw snapshots) stay at the geodatabase root; attribute tables become tables.
* Coded and range domains are created from ``schema.yaml`` and assigned to their fields.
* Subtypes: the schema's subtype fields are text, so an integer ``<field>_code`` is added,
  filled from the domain order and set as the subtype field.
* Relationship classes are created when the licence allows (Standard or Advanced); on a Basic
  licence each one is reported as skipped. The report is written next to the geodatabase.
Raw snapshots are exported only with ``--raw``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import arcpy  # type: ignore[import-not-found]
import yaml

TYPE_MAP = {"coded": "CODED", "range": "RANGE"}


def written_layers(gpkg: Path) -> list[str]:
    con = sqlite3.connect(gpkg)
    try:
        sql = "SELECT layer FROM _ParkIQ_Layers WHERE kind IN ('features', 'attributes')"
        return [r[0] for r in con.execute(sql)]
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpkg", required=True, type=Path)
    ap.add_argument("--schema", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()
    schema = yaml.safe_load(a.schema.read_text(encoding="utf-8"))
    arcpy.env.overwriteOutput = True
    out = a.out
    if arcpy.Exists(str(out)):
        arcpy.management.Delete(str(out))
    arcpy.management.CreateFileGDB(str(out.parent), out.name)
    gdb = str(out)
    rep: dict[str, object] = {"license": arcpy.ProductInfo(), "layers": {}, "skipped": []}

    # domains
    for name, d in schema["domains"].items():
        if d["type"] == "coded":
            arcpy.management.CreateDomain(gdb, name, name, "TEXT", "CODED")
            for v in d["values"]:
                arcpy.management.AddCodedValueToDomain(gdb, name, v, v)
        else:
            arcpy.management.CreateDomain(gdb, name, name, "DOUBLE", "RANGE")
            arcpy.management.SetValueForRangeDomain(gdb, name, d["min"], d["max"])

    layers = {**schema["layers"], **(schema.get("tables") or {})}
    have = set(written_layers(a.gpkg))
    sr = None
    datasets: set[str] = set()
    for name, ldef in layers.items():
        if name not in have or (ldef.get("raw") and not a.raw):
            continue
        src = f"{a.gpkg}\\main.{name}"
        spatial = ldef.get("geometry") is not None and ldef.get("crs") != "none"
        if spatial:
            fd = ldef.get("feature_dataset") if ldef.get("crs") == "analysis" else None
            if fd:
                if sr is None:
                    sr = arcpy.Describe(src).spatialReference
                if fd not in datasets:
                    arcpy.management.CreateFeatureDataset(gdb, fd, sr)
                    datasets.add(fd)
                dst = f"{gdb}\\{fd}\\{name}"
            else:
                dst = f"{gdb}\\{name}"
        else:
            dst = f"{gdb}\\{name}"
        try:
            if spatial:
                arcpy.conversion.ExportFeatures(src, dst)
            else:
                arcpy.conversion.ExportTable(src, dst)
        except arcpy.ExecuteError as exc:
            msg = str(exc).splitlines()[0] if str(exc) else "error"
            rep["skipped"].append(f"{name}: export failed ({msg})")  # type: ignore[union-attr]
            print("FAILED", name, msg, flush=True)
            continue
        print("exported", name, flush=True)
        fields = {f.name for f in arcpy.ListFields(dst)}
        for fname, fdef in (ldef.get("fields") or {}).items():
            dom = fdef.get("domain")
            if dom and fname in fields:
                arcpy.management.AssignDomainToField(dst, fname, dom)
        sub = ldef.get("subtype_field")
        if sub and sub in fields:
            dom = (ldef["fields"][sub] or {}).get("domain")
            values = schema["domains"][dom]["values"] if dom else []
            code = f"{sub}_code"
            arcpy.management.AddField(dst, code, "SHORT")
            with arcpy.da.UpdateCursor(dst, [sub, code]) as cur:
                for row in cur:
                    row[1] = values.index(row[0]) if row[0] in values else None
                    cur.updateRow(row)
            arcpy.management.SetSubtypeField(dst, code)
            for i, v in enumerate(values):
                arcpy.management.AddSubtype(dst, i, v)
        rep["layers"][name] = int(arcpy.management.GetCount(dst)[0])  # type: ignore[index]

    # relationship classes (Standard/Advanced licence)
    def path_of(n: str) -> str | None:
        for fd in [None, *sorted(datasets)]:
            p = f"{gdb}\\{fd}\\{n}" if fd else f"{gdb}\\{n}"
            if arcpy.Exists(p):
                return p
        return None

    for r in schema.get("relationships", []):
        o, d = path_of(r["origin"]), path_of(r["destination"])
        if not o or not d:
            rep["skipped"].append(f"{r['name']}: origin or destination not in this run")  # type: ignore[union-attr]
            continue
        card = {"1:1": "ONE_TO_ONE", "1:M": "ONE_TO_MANY", "M:N": "MANY_TO_MANY"}[r["cardinality"]]
        try:
            arcpy.management.CreateRelationshipClass(
                o, d, f"{gdb}\\{r['name']}", "SIMPLE", r["destination"], r["origin"], "NONE",
                card, "NONE", r["origin_key"], r["destination_key"],
            )
        except arcpy.ExecuteError as exc:
            msg = str(exc).splitlines()[0] if str(exc) else "error"
            rep["skipped"].append(f"{r['name']}: {msg}")  # type: ignore[union-attr]
    (out.parent / (out.stem + "_gdb_report.json")).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({"gdb": gdb, "layers": len(rep["layers"]), "skipped": rep["skipped"]}, indent=1))  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    sys.exit(main())
