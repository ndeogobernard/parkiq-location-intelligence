"""ParkIQ helper: describe any layer - field names/types, row count, CRS, and 5 sample rows - and save
it to 03_tables/<name>_profile.txt for review and for filling the S01 field_map.

Run in the ArcGIS Pro Python window after setting LAYER:
    LAYER = r"C:\\GIS\\ParkIQ_FranklinOH\\01_raw\\S01_parcels\\<your parcels file or fc>"
    exec(open(r"C:\\GIS\\ParkIQ_FranklinOH\\scripts\\02_inspect_layer.py").read())
Works for feature classes, shapefiles, and tables (CSV/DBF/gdb tables).
"""
import os

import arcpy

ROOT = r"C:\GIS\ParkIQ_FranklinOH"
LAYER = globals().get("LAYER") or r"<set LAYER before running>"
N_SAMPLE = 5

desc = arcpy.Describe(LAYER)
fields = [f for f in arcpy.ListFields(LAYER) if f.type not in ("Geometry", "Blob", "Raster")]
lines = [
    f"Layer: {LAYER}",
    f"Type: {desc.dataType}",
    f"Rows: {int(arcpy.management.GetCount(LAYER)[0]):,}",
]
if hasattr(desc, "spatialReference") and desc.spatialReference:
    sr = desc.spatialReference
    lines.append(f"CRS: {sr.name} (WKID {sr.factoryCode}), units {sr.linearUnitName}")
if hasattr(desc, "shapeType"):
    lines.append(f"Geometry: {desc.shapeType}")
lines.append("")
lines.append("FIELDS (name | type | length | alias)")
for f in fields:
    lines.append(f"  {f.name} | {f.type} | {f.length} | {f.aliasName}")
lines.append("")
lines.append(f"SAMPLE ({N_SAMPLE} rows)")
names = [f.name for f in fields]
with arcpy.da.SearchCursor(LAYER, names) as cur:
    for i, row in enumerate(cur):
        if i >= N_SAMPLE:
            break
        lines.append("  " + " | ".join(f"{n}={v}" for n, v in zip(names, row)))

text = "\n".join(lines)
print(text)
base = os.path.splitext(os.path.basename(str(LAYER)))[0] or "layer"
out = os.path.join(ROOT, "03_tables", f"{base}_profile.txt")
with open(out, "w", encoding="utf-8") as fh:
    fh.write(text)
print(f"\nSaved: {out}")
