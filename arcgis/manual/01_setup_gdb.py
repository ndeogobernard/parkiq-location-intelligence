"""ParkIQ - Franklin County, OH - Session 1 (Phase A): geodatabase, domains, boundary, study area, H3 grid.

Requires ArcGIS Pro 3.1+ (H3 option in Generate Tessellation). No extensions needed.

Run ONE of:
  * ArcGIS Pro Python window:  exec(open(r"C:\\GIS\\ParkIQ_FranklinOH\\scripts\\01_setup_gdb.py").read())
  * Command prompt:  "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\scripts\\propy.bat" 01_setup_gdb.py

Re-runnable: outputs are overwritten; domains are created only if missing.
Edit the CONFIG block only.
"""
import datetime
import json
import os

import arcpy

# ------------------------------------------------------------------ CONFIG
ROOT = r"C:\GIS\ParkIQ_FranklinOH"
COUNTY_SHP = os.path.join(ROOT, r"01_raw\S00_boundary\tl_2025_us_county.shp")  # match the year you downloaded
COUNTY_GEOID = "39049"                  # Franklin County, OH
MARKET = "franklin_oh"
SCENARIO = "Balanced"
EPSG = 3735                             # NAD83 / Ohio South (ftUS) - ADR-0007
STUDY_BUFFER = "1 Miles"                # SCOPE 2.2
H3_RESOLUTION = 9                       # SCOPE 2.2 [DECISION] ADR-0009
SOURCE_ID_BOUNDARY = "S00"
# ------------------------------------------------------------------------

GDB_NAME = f"ParkIQ_{MARKET}.gdb"
GDB = os.path.join(ROOT, "02_working", GDB_NAME)
RUN_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M") + f"_{MARKET}_{SCENARIO}"
LOAD_TS = datetime.datetime.now()
SR = arcpy.SpatialReference(EPSG)

arcpy.env.overwriteOutput = True
arcpy.env.outputCoordinateSystem = SR

FEATURE_DATASETS = ["Raw", "Reference", "Cadastral", "Demand", "Supply", "Analysis", "Results"]

# SCOPE 4.4 domains: name -> (field type, "CODED"/"RANGE", values or (min, max))
DOMAINS = {
    "dm_LandUseClass": ("TEXT", "CODED", ["Vacant", "SurfaceParking", "Commercial", "Industrial",
                                          "Residential", "MixedUse", "Institutional", "Other"]),
    "dm_OwnerType": ("TEXT", "CODED", ["Private", "Corporate", "Public", "Institutional", "Unknown"]),
    "dm_ZoningScreen": ("TEXT", "CODED", ["ByRight", "Conditional", "Prohibited", "Unknown"]),
    "dm_AnchorCategory": ("TEXT", "CODED", ["Office", "Medical", "University", "Hotel", "RestaurantBar",
                                            "Retail", "Venue", "Transit", "ResidentialBlock",
                                            "Government", "Other"]),
    "dm_SizeMetric": ("TEXT", "CODED", ["Jobs", "Beds", "Enrollment", "Rooms", "Seats", "Sqft",
                                        "Units", "Count"]),
    "dm_SupplyType": ("TEXT", "CODED", ["Surface", "Garage", "OnStreet", "Mixed"]),
    "dm_Daypart": ("TEXT", "CODED", ["wd_day", "wd_eve", "we_day", "we_eve", "event"]),
    "dm_ScreenStatus": ("TEXT", "CODED", ["Pass", "Fail", "Review"]),
    "dm_Scenario": ("TEXT", "CODED", ["Balanced", "DemandFirst", "CostFirst"]),
    "dm_Direction": ("TEXT", "CODED", ["Benefit", "Cost"]),
    "rg_Score": ("DOUBLE", "RANGE", (0, 100)),
    "rg_Occupancy": ("DOUBLE", "RANGE", (0, 1)),
}


def log(msg: str) -> None:
    """Print to the Pro geoprocessing messages and the console."""
    arcpy.AddMessage(msg)
    print(msg)


def add_lineage(fc: str, source_id: str) -> None:
    """Add and populate source_id, run_id, load_ts (SCOPE 4.2) on a feature class."""
    existing = {f.name for f in arcpy.ListFields(fc)}
    for name, ftype, length in (("source_id", "TEXT", 20), ("run_id", "TEXT", 60), ("load_ts", "DATE", None)):
        if name not in existing:
            arcpy.management.AddField(fc, name, ftype, field_length=length)
    with arcpy.da.UpdateCursor(fc, ["source_id", "run_id", "load_ts"]) as cur:
        for _ in cur:
            cur.updateRow([source_id, RUN_ID, LOAD_TS])


def create_gdb() -> None:
    """Create the file geodatabase and the seven feature datasets (SCOPE 4.2)."""
    if not arcpy.Exists(GDB):
        arcpy.management.CreateFileGDB(os.path.dirname(GDB), GDB_NAME)
        log(f"Created {GDB}")
    for fd in FEATURE_DATASETS:
        if not arcpy.Exists(os.path.join(GDB, fd)):
            arcpy.management.CreateFeatureDataset(GDB, fd, SR)
            log(f"  feature dataset {fd}")


def create_domains() -> None:
    """Create SCOPE 4.4 coded-value and range domains if they don't exist."""
    have = {d.name for d in arcpy.da.ListDomains(GDB)}
    for name, (ftype, dtype, values) in DOMAINS.items():
        if name in have:
            continue
        arcpy.management.CreateDomain(GDB, name, name, ftype, dtype)
        if dtype == "CODED":
            for v in values:
                arcpy.management.AddCodedValueToDomain(GDB, name, v, v)
        else:
            arcpy.management.SetValueForRangeDomain(GDB, name, values[0], values[1])
        log(f"  domain {name}")


def build_boundary() -> tuple[str, str]:
    """Market boundary (projected) and 1-mile study area."""
    if not arcpy.Exists(COUNTY_SHP):
        raise FileNotFoundError(f"County shapefile not found: {COUNTY_SHP}")
    lyr = arcpy.management.MakeFeatureLayer(COUNTY_SHP, "county_lyr", f"GEOID = '{COUNTY_GEOID}'")
    n = int(arcpy.management.GetCount(lyr)[0])
    if n != 1:
        raise ValueError(f"Expected 1 county with GEOID {COUNTY_GEOID}, found {n}")
    boundary = os.path.join(GDB, "Reference", "MarketBoundary")
    arcpy.management.Project(lyr, boundary, SR)  # TIGER is NAD83 (4269) -> 3735: same datum, no transformation
    arcpy.management.AddField(boundary, "area_sqmi", "DOUBLE")
    arcpy.management.CalculateGeometryAttributes(boundary, [["area_sqmi", "AREA"]], area_unit="SQUARE_MILES_US")
    add_lineage(boundary, SOURCE_ID_BOUNDARY)

    study = os.path.join(GDB, "Reference", "StudyArea")
    arcpy.analysis.Buffer(boundary, study, STUDY_BUFFER, dissolve_option="ALL")
    add_lineage(study, SOURCE_ID_BOUNDARY)
    area = [r[0] for r in arcpy.da.SearchCursor(boundary, ["area_sqmi"])][0]
    log(f"MarketBoundary area: {area:,.1f} sq mi; StudyArea = boundary + {STUDY_BUFFER}")
    return boundary, study


def build_hex_grid(study: str) -> str:
    """H3 resolution-9 grid for hexes whose centre is in the study area, plus centroids."""
    tmp = os.path.join(GDB, "tmp_h3_tess")
    extent = arcpy.Describe(study).extent
    try:
        arcpy.management.GenerateTessellation(tmp, extent, "H3_HEXAGON", None, SR, H3_RESOLUTION)
    except arcpy.ExecuteError:
        log("Generate Tessellation with H3 failed. Check ArcGIS Pro >= 3.1 and the tool's Shape Type list; "
            "report the error text back.")
        raise

    fields = [f.name for f in arcpy.ListFields(tmp)]
    h3_field = next((f for f in fields if "H3" in f.upper()), None) or ("GRID_ID" if "GRID_ID" in fields else None)
    if h3_field is None:
        raise RuntimeError(f"No H3/GRID_ID field found in tessellation output. Fields: {fields}")
    log(f"Tessellation ID field used: {h3_field}")

    lyr = arcpy.management.MakeFeatureLayer(tmp, "h3_lyr")
    arcpy.management.SelectLayerByLocation(lyr, "HAVE_THEIR_CENTER_IN", study)
    hexes = os.path.join(GDB, "Reference", "HexGrid")
    arcpy.management.CopyFeatures(lyr, hexes)
    arcpy.management.Delete(tmp)

    arcpy.management.AddField(hexes, "hex_id", "TEXT", field_length=20)
    arcpy.management.CalculateField(hexes, "hex_id", f"str(!{h3_field}!)", "PYTHON3")
    arcpy.management.AddField(hexes, "submarket", "TEXT", field_length=60)
    arcpy.management.AddField(hexes, "area_km2", "DOUBLE")
    arcpy.management.CalculateGeometryAttributes(hexes, [["area_km2", "AREA"]], area_unit="SQUARE_KILOMETERS")
    add_lineage(hexes, "DERIVED")

    centroids = os.path.join(GDB, "Reference", "HexCentroids")
    arcpy.management.FeatureToPoint(hexes, centroids, "INSIDE")
    add_lineage(centroids, "DERIVED")

    n = int(arcpy.management.GetCount(hexes)[0])
    areas = [r[0] for r in arcpy.da.SearchCursor(hexes, ["area_km2"])]
    ids = [r[0] for r in arcpy.da.SearchCursor(hexes, ["hex_id"])]
    log(f"HexGrid: {n:,} hexes; mean area {sum(areas)/n:.4f} km2 (H3 r9 average is ~0.105); "
        f"duplicate hex_id: {len(ids) - len(set(ids))}")
    return hexes


def main() -> None:
    log(f"RUN_ID {RUN_ID}")
    create_gdb()
    create_domains()
    _, study = build_boundary()
    hexes = build_hex_grid(study)
    run_log = {
        "run_id": RUN_ID, "session": 1, "phase": "A (setup)", "gdb": GDB, "epsg": EPSG,
        "county_geoid": COUNTY_GEOID, "county_source": COUNTY_SHP, "study_buffer": STUDY_BUFFER,
        "h3_resolution": H3_RESOLUTION, "hex_count": int(arcpy.management.GetCount(hexes)[0]),
        "arcgis_pro_version": arcpy.GetInstallInfo().get("Version"), "timestamp": LOAD_TS.isoformat(),
    }
    out = os.path.join(ROOT, "00_admin", "run_logs", f"{RUN_ID}_session1.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(run_log, fh, indent=2)
    log(f"Run log written: {out}")
    log("Session 1 setup complete.")


main()
