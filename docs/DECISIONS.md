# ParkIQ — Decision Log (ADRs)

One register for every method choice. It merges two earlier registers whose IDs overlapped:

* **Plan ID** = the original implementation plan's decision list (D-01 … D-40)
* **Admin ID** = `docs/reference/ParkIQ_FranklinOH_Admin.xlsx` → Decision_Log (D-01 … D-15),
  the manual pilot's decision log

Decisions are cited by **ADR number**; the two ID columns keep the older IDs traceable.
Status: **Accepted** = confirmed; **Proposed** = recorded, awaiting confirmation (both registers
agree unless noted); **Open** = needs a call before the milestone shown.

## Index

| ADR | Topic | Plan ID | Admin ID | Status | Needed by |
|---|---|---|---|---|---|
| 0001 | Pilot market = Franklin County, OH (GEOID 39049) | Q10 | D-01 | **Accepted** 2026-09-24 | — |
| 0002 | Build path: code toolkit, Franklin as pilot, manual method = reference spec | — | — | **Accepted** 2026-09-24 | — |
| 0003 | Repo `C:\GIS\ParkIQ`; env `C:\GIS\envs\parkiq` (ArcGIS Pro's conda, separate env) | Q9 | — | **Accepted** 2026-09-24 | — |
| 0004 | Network backend = OSMnx + pandana | D-02 | D-05 | **Accepted** 2026-09-24 | — |
| 0005 | Brief-over-scope precedence; `StudyArea` layer added | D-04 | — | Proposed | — |
| 0006 | Intermediate standardized input layers (Places, BlockJobs, …) | — | — | Proposed | M2 |
| 0007 | Analysis CRS for Franklin = EPSG:3735 (ftUS) | — | D-02 | Proposed | — |
| 0008 | Two-stage study extent (county scan → focus submarkets) | — | D-03 | Proposed (amended) | M4 |
| 0009 | Grid = H3 r9 (h3-py v4, centroid rule) | D-01 | D-04 | Proposed | — |
| 0010 | One GeoPackage per run | D-05 | — | Proposed | M2 |
| 0011 | GDB concepts mapped onto GeoPackage | D-06 | — | Proposed | M2 |
| 0012 | Rasters as GeoTIFF beside the GeoPackage | D-07 | — | Proposed | — |
| 0013 | Demand-/supply-conserving walk-shed allocation | D-08 | D-08 | Proposed | M3 |
| 0014 | Mode-share adjustment = local ÷ rate-source baseline | D-09 | D-06 | Proposed | M4 |
| 0015 | Residential demand input | D-10 | D-07 | **Open** | M4 |
| 0016 | `.pyt` shells out to the CLI in the parkiq env | D-11 | — | Proposed | M7 |
| 0017 | Market `ranking:` overrides shared weights | D-12 | — | Proposed | — |
| 0018 | Microsoft footprints via Overture (no separate adapter) | D-13 | — | Proposed | — |
| 0019 | Units in field names; conversions only in `parkiq/units.py` | D-14 | — | Proposed | — |
| 0020 | Supply dedupe rule | D-15 | — | Proposed | M3 |
| 0021 | On-street curb length | D-16 | — | Proposed | M3 |
| 0022 | Anchor category crosswalk `configs/anchor_crosswalk.yaml` | D-17 | — | Proposed | M4 |
| 0023 | Listing-rate → daypart mapping | D-18 | — | Proposed | M3 |
| 0024 | Hot-zone contiguity = H3 k=1 components | D-19 | — | Proposed | M4 |
| 0025 | Shape index = rectangularity | D-20 | D-09 | Proposed | M5 |
| 0026 | Frontage / corner definitions | D-21 | — | Proposed | M5 |
| 0027 | Walk-shed polygons = buffered reachable edges | D-22 | — | Proposed | M5 |
| 0028 | Criteria C01–C10 measurement details | D-23 | — | Proposed | M5 |
| 0029 | Dirichlet sensitivity = flat (α = 1) | D-24 | D-11 | Proposed | M5 |
| 0030 | 40–200 candidate rule: report, don't auto-adjust | D-25 | — | Proposed | M5 |
| 0031 | Size vs stall range: apply both | Q2 | D-10 | Proposed | M5 |
| 0032 | Occupancy = min(cap, g(gap_ratio), absorption) | D-26 | D-12 | Proposed | M6 |
| 0033 | Billing basis / days / event overlap | D-27 | — | Proposed | M6 |
| 0034 | Monthly permits rule | D-28 | — | Proposed | M6 |
| 0035 | Opex structure | D-29 | — | Proposed | M6 |
| 0036 | Property-tax base | D-30 | — | Proposed | M6 |
| 0037 | Returns convention (unlevered, exit, lease reversion) | D-31 | — | Proposed | M6 |
| 0038 | Payback definition | D-32 | — | Proposed | M6 |
| 0039 | Ground-lease rent | D-33 | — | Proposed | M6 |
| 0040 | Soft cost base = hard cost | — | D-13 | Proposed | M6 |
| 0041 | Financial ranking metric = yield-on-cost (buy) | D-34 | D-14 | Proposed | M6 |
| 0042 | Excel parity engine (`formulas`, no cached values) | D-35 | — | Proposed | M6 |
| 0043 | Calibration factors in `markets/<slug>.calibration.yaml` | D-36 | — | Proposed | M8 |
| 0044 | CLI names: `check-config` validates config; `validate` = back-test | D-37/Q3 | — | Proposed | — |
| 0045 | `.gdb` export optional (`package --gdb`) | D-38 | — | Proposed | M7 |
| 0046 | Due-diligence flags are rule-based | D-39 | — | Proposed | M6 |
| 0047 | Memo numbers carry a trace key | D-40 | — | Proposed | M7 |
| 0048 | Zoning screen table for Columbus | — | D-15 | Proposed | M2 |
| 0049 | Stall count rounds down | — | (manual §9.1) | Proposed | M5 |
| 0050 | Config provenance (`provenance:` map) and step gating | Q6 | — | Proposed | — |
| 0051 | `configs/sources.yaml` source catalogue; S03 split into S03a/S03b | Q4 | — | Proposed | — |
| 0052 | Runtime environment on managed Windows workstations | — | — | Proposed | — |
| 0053 | Ingest geometry rules (clip, repair, dedupe) | — | — | Proposed | — |
| 0054 | Manual observations CSV for rates/occupancy | Q1 | S07 row | Proposed | M2 |

---

## ADR-0001 — Pilot market
**Decision:** Franklin County, OH (GEOID 39049), slug `franklin_oh`. Confirmed 2026-09-24.
**Consequence:** M1's SCOPE exit ("pilot market boundary and network built") is tested live on
Franklin, in addition to the offline fixture.

## ADR-0002 — Build path
**Decision:** Build the automated toolkit in eight milestones (docs/ARCHITECTURE.md §7).
`docs/MANUAL_METHODOLOGY.md` is the method reference; where it is more specific than the plan
(worked formulas, reason codes, templates), the code follows the manual and says so here. The
ArcPy scripts from the manual start are kept under `arcgis/manual/` (Session-1 GDB setup; layer
inspector).

## ADR-0003 — Locations and environment
**Decision:** Code at `C:\GIS\ParkIQ` (outside OneDrive). Runs and caches go to
`C:\GIS\ParkIQ\outputs\` (gitignored), or wherever `PARKIQ_OUTPUT_ROOT` points. Python 3.11 conda
env at `C:\GIS\envs\parkiq`, created with ArcGIS Pro's `conda.exe`; `arcgispro-py3` is untouched.

## ADR-0004 — Network backend
**Decision:** OSMnx builds the walk graph; pandana will do bulk travel times (M4); networkx for
walk-shed polygons (M5). Network Analyst is not used in the core (it would also break the
"no arcpy in parkiq/" rule).

## ADR-0005 — Precedence and `StudyArea`
Where the build brief is more specific than SCOPE, the brief wins and the difference is logged
here. SCOPE §2.2 defines the study area (boundary + 1 mile) but §4.2 has no layer for it. **Added:** `Reference/StudyArea`, the manual's
§4.1 clip extent.

## ADR-0006 — Intermediate standardized layers
SCOPE §4.2 has no home for standardized inputs that later phases need but that are not themselves
SCOPE layers. **Added (analysis CRS, with lineage):** `Places` (Overture + OSM POIs),
`BlockJobs` (LODES), `BlockGroups` (ACS), `Hospitals`, `Institutions` (IPEDS), `ParkingOSM`,
`TrafficCounts` (AADT), `FloodHazard` (NFHL), `EnvSites` (EPA). They feed `DemandAnchors` (M4),
`SupplyFacilities` (M3) and candidate flags (M5); they are inputs, not new outputs. Raw snapshots
are `Raw_*` in EPSG:4326 (SCOPE §4.5 versioning).

## ADR-0007 — Franklin analysis CRS
EPSG:3735 NAD83 / Ohio South (ftUS). It matches the Auditor parcel service, so the largest layer
needs no reprojection. `check-config` enforces `units: ft` against the CRS itself.

## ADR-0008 — Study extent (amended)
Admin D-03 proposed a two-stage process: a county-wide demand scan, then 1–3 focus submarkets,
because the manual network work scales poorly. With code, the network and grid run for the whole
county, so the scan is no longer a workload constraint. **Proposed amendment:** run the full county
end to end; use the scan only to pick `focus_submarkets` for reporting and insets (SCOPE §2.2: not a
filter).

## ADR-0009 — H3 grid
H3 r9 via h3-py v4 `geo_to_cells` (centroid containment, the same as the manual's
"hexes whose centre is in StudyArea"). Hex IDs will match ArcGIS Pro's Generate Tessellation H3 IDs.
**Amendment (found on the live Franklin run, 2026-09-24):** at a narrow concave inlet of the
buffered boundary (east Franklin, near the Fairfield/Licking line) the centroid rule excluded one
cell whose six neighbours were all included, leaving an enclosed hole. SCOPE §4.5 forbids gaps, so
cells inside any hole of the grid's union are added, and the number is recorded in the setup summary
(`hex_filled_holes`; Franklin: 1). The manual's ArcPy script (`01_setup_gdb.py`,
`HAVE_THEIR_CENTER_IN`) would leave the same hole, so a manual reference grid for Franklin should
be expected to differ by this one cell.

## ADR-0010 — One GeoPackage per run
`outputs/<market>/<run_id>/ParkIQ_<market>.gpkg`, self-contained incl. `Raw_*`; shared download
cache `outputs/<market>/_cache/`. Idempotency = a step rewrites its own layers; shared tables
delete `WHERE run_id AND key` first.

## ADR-0011 — GeoPackage mapping
docs/ARCHITECTURE.md §3 table. M1 enforces domains, types, nullability and uniqueness at write time from
`schema/schema.yaml`, and keeps a `_ParkIQ_Layers` registry (feature dataset, geometry, CRS). M2
adds GeoPackage schema-extension constraints and related tables.

## ADR-0012 — Rasters
GeoTIFF in `rasters/` (e.g. `Slope_pct.tif`, float32, deflate), registered in `_ParkIQ_Layers`.
Slope = Horn 3×3 percent rise; z-factor from DEM units ÷ CRS units (m → ftUS = 3.28083); a nodata
centre cell stays nodata.

## ADR-0013 … ADR-0047
As listed in the index (plan D-08 … D-40 and the admin Decision_Log). Each is **Proposed**; the
plan and the manual pilot's workbook agree wherever both cover a topic. They will be restated here
in full, with anything
learned during the build, at the milestone that needs them.
**ADR-0015 is Open:** set `demand.residential_offstreet_share` or exclude residential demand.

## ADR-0048 — Columbus zoning screen (ADMIN D-15)
Build the `zoning_screen` table covering Title 33, Title 34 (Zone In) and Downtown zones A/B;
suburbs separately. [VERIFY current code] Joined in M2 (S23).

## ADR-0049 — Stall rounding
Buildable stalls = `ROUNDDOWN(lot_sqft × (1 − setback) × efficiency ÷ stall_area, 0)`
(manual §9.1 / App. C). The plan did not specify rounding; the code follows the manual so the Python
figures, the Excel model and the manual reference agree.

## ADR-0050 — Provenance and step gating
Each config YAML carries a `provenance:` map `{dotted.path: {status, source}}`, using the
workbook's status vocabulary (SCOPE / VERIFY / SET / DECIDE). DECIDE parameters are `null`. Each
step declares the dotted paths it needs (`parkiq.config.STEP_REQUIREMENTS`), and the runner refuses
to run it while any is null. Nothing is defaulted in code. `check-config --report x.csv` writes
the parameter table in the workbook's layout. Numeric values without provenance are reported as
UNTAGGED.

## ADR-0051 — Source catalogue
`configs/sources.yaml` holds every source's provider, license, URL template, `[VERIFY]` flag and
option defaults (e.g. OSM tag queries). A market's `sources:` block overrides per key. SCOPE's S03
combines two datasets, so the registry uses **S03a** (Overture Places) and **S03b** (OSM POIs); the
same applies to S12a (hospitals) and S12b (IPEDS), as in the workbook. Option keys ending in
`_path` are file paths, resolved relative to the market file.

## ADR-0052 — Runtime environment on managed Windows workstations
1. **PATH:** other software on a workstation PATH can ship its own `geos_c.dll`,
   `spatialite.dll`, `libxml2.dll` and ICU; conda-forge Python may load those ("DLL load failed …
   procedure could not be found"). `scripts/parkiq-env.ps1` / `.sh` put the env first and keep
   only system folders **for that shell session**. No system change.
2. **TLS:** on networks that inspect HTTPS with an organisation root certificate, conda and Python
   verify against the **OS certificate store** (`CONDA_SSL_VERIFY=truststore` for conda; the
   `truststore` package for Python, injected in `parkiq/__init__.py`). Certificate verification is
   never disabled.

## ADR-0053 — Ingest geometry rules
Features are reprojected to the analysis CRS, invalid geometry is repaired (`make_valid`), and
null/empty geometry is dropped. Features are **kept whole if they intersect** StudyArea (no
cutting, so no slivers). Parcels that share a `parcel_id` (multipart) are dissolved, with the count
noted. Unmatched land-use codes → `Other` (counted); owners matching no rule → `Unknown`.

## ADR-0054 — Manual observations
The analyst's field survey (workbook S07 row; manual App. D/E templates) is ingested by
`manual_observations.py` (M2), in place of app listings unless those are licensed. Never mocked.
