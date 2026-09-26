# ParkIQ — Decision Log (ADRs)

One register for every method choice. It merges two earlier registers whose IDs overlapped:

* **Plan ID** = the original implementation plan's decision list (D-01 … D-40)
* **Admin ID** = `docs/reference/ParkIQ_FranklinOH_Admin.xlsx` → Decision_Log (D-01 … D-15),
  the manual pilot's decision log

Decisions are cited by **ADR number**; the two ID columns keep the older IDs traceable.
Status: **Accepted** = confirmed; **Proposed — review at Mx** = recorded but not confirmed; at the
start of milestone Mx each such ADR is restated in plain language with its Franklin-specific
consequence and confirmed before any code builds on it.

## Index

| ADR | Topic | Plan ID | Admin ID | Status | Needed by |
|---|---|---|---|---|---|
| 0001 | Pilot market = Franklin County, OH (GEOID 39049) | Q10 | D-01 | **Accepted** 2026-09-24 | — |
| 0002 | Build path: code toolkit, Franklin as pilot, manual method = reference spec | — | — | **Accepted** 2026-09-24 | — |
| 0003 | Repo `C:\GIS\ParkIQ`; env `C:\GIS\envs\parkiq` (ArcGIS Pro's conda, separate env) | Q9 | — | **Accepted** 2026-09-24 | — |
| 0004 | Network backend = OSMnx + pandana | D-02 | D-05 | **Accepted** 2026-09-24 | — |
| 0005 | Brief-over-scope precedence; `StudyArea` layer added | D-04 | — | **Accepted** 2026-09-24 | — |
| 0006 | Intermediate standardized input layers (Places, BlockJobs, …) | — | — | **Accepted** 2026-09-24 | M2 |
| 0007 | Analysis CRS for Franklin = EPSG:3735 (ftUS) | — | D-02 | **Accepted** 2026-09-24 | — |
| 0008 | Two-stage study extent (county scan → focus submarkets) | — | D-03 | **Accepted** 2026-09-24 | M4 |
| 0009 | Grid = H3 r9 (h3-py v4, centroid rule) | D-01 | D-04 | **Accepted** 2026-09-24 | — |
| 0010 | One GeoPackage per run | D-05 | — | **Accepted** 2026-09-24 | M2 |
| 0011 | GDB concepts mapped onto GeoPackage | D-06 | — | **Accepted** 2026-09-24 | M2 |
| 0012 | Rasters as GeoTIFF beside the GeoPackage | D-07 | — | **Accepted** 2026-09-24 | — |
| 0013 | Demand-/supply-conserving walk-shed allocation | D-08 | D-08 | **Accepted** 2026-09-24 | M3 |
| 0014 | Mode-share adjustment = local ÷ rate-source baseline | D-09 | D-06 | **Accepted** 2026-09-24 | M4 |
| 0015 | Residential demand input — excluded for the Franklin pilot | D-10 | D-07 | **Accepted** 2026-09-24 | M4 |
| 0016 | `.pyt` shells out to the CLI in the parkiq env | D-11 | — | **Accepted** 2026-09-24 | M7 |
| 0017 | Market `ranking:` overrides shared weights | D-12 | — | **Accepted** 2026-09-24 | — |
| 0018 | Microsoft footprints via Overture (no separate adapter) | D-13 | — | **Accepted** 2026-09-24 | — |
| 0019 | Units in field names; conversions only in `parkiq/units.py` | D-14 | — | **Accepted** 2026-09-24 | — |
| 0020 | Supply dedupe rule | D-15 | — | Proposed — **review at M3** | M3 |
| 0021 | On-street curb length | D-16 | — | Proposed — **review at M3** | M3 |
| 0022 | Anchor category crosswalk `configs/anchor_crosswalk.yaml` | D-17 | — | **Accepted** 2026-09-24 | M4 |
| 0023 | Listing-rate → daypart mapping | D-18 | — | Proposed — **review at M3** | M3 |
| 0024 | Hot-zone contiguity = H3 k=1 components | D-19 | — | Proposed — **review at M4** | M4 |
| 0025 | Shape index = rectangularity | D-20 | D-09 | **Accepted** 2026-09-24 | M5 |
| 0026 | Frontage / corner definitions | D-21 | — | Proposed — **review at M5** | M5 |
| 0027 | Walk-shed polygons = buffered reachable edges | D-22 | — | **Accepted** 2026-09-24 | M5 |
| 0028 | Criteria C01–C10 measurement details | D-23 | — | Proposed — **review at M5** | M5 |
| 0029 | Dirichlet sensitivity = flat (α = 1) | D-24 | D-11 | **Accepted** 2026-09-24 | M5 |
| 0030 | 40–200 candidate rule: report, don't auto-adjust | D-25 | — | **Accepted** 2026-09-24 | M5 |
| 0031 | Size vs stall range: apply both | Q2 | D-10 | **Accepted** 2026-09-24 | M5 |
| 0032 | Occupancy = min(cap, g(gap_ratio), absorption) | D-26 | D-12 | **Accepted** 2026-09-24 | M6 |
| 0033 | Billing basis / days / event overlap | D-27 | — | Proposed — **review at M6** | M6 |
| 0034 | Monthly permits rule | D-28 | — | Proposed — **review at M6** | M6 |
| 0035 | Opex structure | D-29 | — | Proposed — **review at M6** | M6 |
| 0036 | Property-tax base | D-30 | — | Proposed — **review at M6** | M6 |
| 0037 | Returns convention (unlevered, exit, lease reversion) | D-31 | — | Proposed — **review at M6** | M6 |
| 0038 | Payback definition | D-32 | — | Proposed — **review at M6** | M6 |
| 0039 | Ground-lease rent | D-33 | — | Proposed — **review at M6** | M6 |
| 0040 | Soft cost base = hard cost | — | D-13 | **Accepted** 2026-09-24 | M6 |
| 0041 | Financial ranking metric = yield-on-cost (buy) | D-34 | D-14 | **Accepted** 2026-09-24 | M6 |
| 0042 | Excel parity engine (`formulas`, no cached values) | D-35 | — | **Accepted** 2026-09-24 | M6 |
| 0043 | Calibration factors in `markets/<slug>.calibration.yaml` | D-36 | — | **Accepted** 2026-09-24 | M8 |
| 0044 | CLI names: `check-config` validates config; `validate` = back-test | D-37/Q3 | — | **Accepted** 2026-09-24 | — |
| 0045 | `.gdb` export optional (`package --gdb`) | D-38 | — | **Accepted** 2026-09-24 | M7 |
| 0046 | Due-diligence flags are rule-based | D-39 | — | **Accepted** 2026-09-24 | M6 |
| 0047 | Memo numbers carry a trace key | D-40 | — | **Accepted** 2026-09-24 | M7 |
| 0048 | Zoning screen table for Columbus | — | D-15 | **Accepted** 2026-09-24 | M2 |
| 0049 | Stall count rounds down | — | (manual §9.1) | **Accepted** 2026-09-24 | M5 |
| 0050 | Config provenance (`provenance:` map) and step gating | Q6 | — | **Accepted** 2026-09-24 | — |
| 0051 | `configs/sources.yaml` source catalogue; S03 split into S03a/S03b | Q4 | — | **Accepted** 2026-09-24 | — |
| 0052 | Runtime environment on managed Windows workstations | — | — | **Accepted** 2026-09-24 | — |
| 0053 | Ingest geometry rules (clip, repair, dedupe) | — | — | **Accepted** 2026-09-24 | — |
| 0054 | Manual observations CSV for rates/occupancy | Q1 | S07 row | **Accepted** 2026-09-24 | M2 |
| 0055 | Optional public-redaction mode for packages (`package --public`) | — | — | **Accepted** 2026-09-24 | M7 |
| 0056 | Download cache outside the repo; DEM fetched once for the study-area extent | — | — | **Accepted** 2026-09-24 | M2 |
| 0057 | Secrets only from the environment; never persisted or logged | — | — | **Accepted** 2026-09-24 | — |
| 0058 | Columbus §3389.131: special permit applies to temporary lots only | — | D-15 | **Accepted** 2026-09-24 ([VERIFY] with Building & Zoning Services) | M5 |
| 0059 | Zoning screen: confidence routing, L- overlays, overlays, GIS code matching | — | D-15 | **Accepted** 2026-09-24 | M5 |

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

## ADR-0008 — Study extent (amended) — Accepted 2026-09-24
Admin D-03 proposed a two-stage process: a county-wide demand scan, then 1–3 focus submarkets,
because the manual network work scales poorly. With code, the network and grid run for the whole
county, so the scan is no longer a workload constraint. **Accepted amendment:** run the full county
end to end; use the scan only to pick `focus_submarkets` for reporting and insets (SCOPE §2.2: not a
filter).

## ADR-0009 — H3 grid — Accepted 2026-09-24 (incl. hole-fill amendment)
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
**ADR-0015 — Residential demand: Accepted 2026-09-24.** Residential demand is **excluded** for the
Franklin pilot. The residential rate row stays in `configs/parking_rates.yaml`; generation is switched
off by configuration (`demand.excluded_anchor_categories: [ResidentialBlock]` in the market file), not
by code. The investment memo's assumptions section must state this exclusion. Revisit after the
Phase K validation back-test.

## ADR-0048 — Columbus zoning screen (ADMIN D-15)
Build the `zoning_screen` table covering Title 33, Title 34 (Zone In) and Downtown zones A/B;
suburbs separately. [VERIFY current code] Joined in M2 (S23).

## ADR-0049 — Stall rounding — Accepted 2026-09-24
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

## ADR-0055 — Optional public-redaction mode
`parkiq package --public` (default **off**) produces a publishable package: parcel IDs, owner names
and addresses are redacted and financial figures are rounded; the choice of what deal detail to
publish is made per release. In every mode: licensed data is never published, and every map that
uses OSM data carries "© OpenStreetMap contributors". Implemented with the package step (M7).

## ADR-0056 — Download cache outside the repository
Raw downloads are cached once per market in `<cache root>/<market>/<source_id>/<vintage>/`, where
the cache root is `PARKIQ_CACHE_ROOT` or, by default, a `ParkIQ_cache` folder beside the
repository — never inside it and never re-downloaded per run. The DEM (S18) is fetched once for the
study-area extent at ~10 m (3DEP ImageServer export if it serves the extent, otherwise tiles);
slope matters little in central Columbus, so effort here stays minimal.

## ADR-0057 — Secrets
API keys (e.g. `CENSUS_API_KEY`) are read only from environment variables named in the config.
They are never written to configs, `params.yaml`, logs, registry rows, error messages or context
files; URLs are redacted before they are logged or raised.

## ADR-0058 — Columbus §3389.131 (special permit for non-accessory parking lots)
**Context.** §3389.131 ("Temporary parking lot") states: "A special permit shall be required for the
establishment of any nonaccessory parking lot. The board of zoning adjustment shall grant a special
permit for a temporary parking lot only when …". C-3 (§3355.03/.05(D)), C-4 (§3356.03/.05(F)) and M
(§3363.01) list parking lots as permitted uses.
**Readings.** (A) The sentence governs *temporary* lots only — supported by the section title and by
Title 34 Table E.20.100.A, which marks non-accessory lots *Allowed* in CAC/RAC and footnotes only
temporary lots as needing a special permit. (B) It requires a Board of Zoning Adjustment special
permit for *every* non-accessory lot.
**Decision.** Reading (A). C-3, C-4 and M are ByRight (confidence Medium).
**Effect of the alternative.** Under (B), C-3, C-4 and M become Conditional: they still pass the
screen but score 60 instead of 100 on C09 (zoning certainty), and the due-diligence list gains
"BZA special permit". Title 34 CAC/RAC are unaffected.
**Status.** [VERIFY] — Bernard is confirming with Columbus Building & Zoning Services; the rows keep
[VERIFY] until he reports back.

## ADR-0059 — Zoning screen rules
The market zoning table (`markets/franklin_oh/zoning_screen.csv`) gives each district a
`commercial_parking_use` (dm_ZoningScreen), a `confidence` (High/Medium/Low) with a one-line reason,
and citations. `parkiq.zoning` resolves a parcel:
* ByRight/Conditional → Pass; Unknown → Review; Prohibited → Fail, **but Low-confidence Prohibited →
  Review** (non-exhaustive use lists such as C-1 or East Franklinton, and every "not listed" reading).
* **Limited (L-) overlays** take the base district's result and are **always Review** with reason
  "limitation text applies". CPD/PUD/PC are Unknown → Review.
* **Overlays** (§3372 UCO/CCO/RCO; §3325 University District) cap the result — the parcel gets the
  more restrictive of base and overlay. UCO/CCO/RCO keep base uses (§3372.05) and add their design
  rule to the reason; University District NC/RC subareas route to Review (lots must sit behind a
  principal building, §3325.231/.331).
* **GIS code matching**: the city layer stores Title 33 codes without hyphens and fuses the L prefix
  (`C4`, `LC4`, `LAR12`); Title 34 codes keep hyphens (`UCR-R`). Matching is hyphen-insensitive,
  exact matches win (so `LRR` is the Limited Rural Residential district, not L + RR), then market
  aliases (`RURAL` → `R`), then density suffixes (`PUD8` → PUD), then the L prefix.
* Jurisdictions not in the table (Dublin, Worthington, Upper Arlington, …) → Unknown → Review,
  never Fail. The screen reason always shows district, result, confidence and citation.
* **Revision (F3 review, 2026-09-25).** Residential, apartment and manufactured-home districts are
  Prohibited with **High** confidence ("commercial pay lot not a permitted principal use in
  residential districts", SCOPE §5.5) and Fail. Low-confidence Prohibited (→ Review) is kept only
  for genuinely ambiguous districts: C-1, C-2, EFD, the TND districts, M-2, EQ. DD with an unknown
  parking zone is **Unknown → Review** (Zone A prohibits new lots). A DD parcel within
  `sources.S23c.options.boundary_review_ft` (150 ft) of the digitized Zone A/B line is always Review
  ("near digitized Zone A/B boundary"), whichever side it falls on (ADR-0061).
* Owner type is a due-diligence flag only, never a screen filter.

## ADR-0060 — M2 schema completion (schema.yaml v1.0.0)
**Decision.** `schema.yaml` now carries every SCOPE §4.2–4.3 class and table, plus:
* **Additions:** `ZoningDistricts`, `ZoningOverlays`, `ParkingZones` (Reference); Parcels fields
  `jurisdiction`, `auto_oriented_flag`, `excluded_use_flag`, `zoning_overlays`, `parking_zone`,
  `parking_zone_near_boundary`, `zoning_status`, `zoning_reason`; domains `dm_Tenure` (Buy/Lease)
  and `dm_ParkingZone` (A/B); raw snapshots `Raw_Zoning`, `Raw_ZoningOverlays`, `Raw_ParkingZones`.
* **Hex × daypart outputs are attribute tables** (`Hex_Demand_Daypart`, `Hex_Supply_Daypart`,
  `Hex_Gap_Daypart`) keyed by `hex_id` and joined to `HexGrid` for display — SCOPE allows
  "Polygon/table"; this avoids storing every hexagon five times.
* **`SupplyFacilities` is a point class** (one point per facility, footprint in `area_sqft`); a
  GeoPackage/FGDB class holds one geometry type.
* **`SiteFinancials`** keeps SCOPE's 1:1 relationship with one row per tenure.
* **Domains** are stored as GeoPackage schema-extension constraints (`gpkg_data_columns` +
  `gpkg_data_column_constraints`), re-attached after every write, and enforced in Python on write.
  **Relationship classes and subtypes** are recorded in `_ParkIQ_Relationships` / `_ParkIQ_Subtypes`
  and become real relationship classes in the file-geodatabase export (M7); GeoPackage has no
  relationship class ArcGIS reads.
* BuildSchema creates all layers empty in every run's GeoPackage; only layers a step actually
  wrote are registered in `_ParkIQ_Layers`, QA-checked and added to the ArcGIS workspace.
* `docs/ERD.drawio`, `docs/ERD.png` and `docs/DataDictionary.md` are generated (`parkiq
  schema-docs`); a test fails if they are out of date.

## ADR-0061 — Downtown parking zones A/B derived from Map 2 (S23c)
**Context.** §3359.27 applies Zone A (no new non-accessory surface lots) and Zone B (permitted with
a Certificate of Appropriateness) "as indicated on the official city zoning map and as illustrated
on Map 2". No GIS layer is published (open data and map services checked 2026-09-24).
**Decision (Bernard, F3, 2026-09-25).** Digitize from Map 2 as derived source S23c, [VERIFY]:
Map 2 (Ord. 1532-2013, Municode image dated 2026-07-01) is georeferenced to TIGER 2025 centerlines
(six intersection control points, affine refined by chamfer matching of all centerlines to the
map's street lines: median residual 0.56 px ≈ 4 ft at 7.13 ft/px). Pixels are classified Zone A /
Zone B by their map shade inside the overlay outline; each parcel takes the zone covering most of
its area; zone polygons are the dissolved parcels — boundaries follow parcel lines, never a
freehand trace. Parcels within 150 ft of the A/B line route to Review. If the City confirms an
official layer, it replaces S23c.


## ADR-0062 — FEMA NFHL query: drop minimal-hazard zones, ~1 m generalization
**Context.** NFHL layer 28 returns full-detail polygons (~75 KB each; 200 features ≈ 15 MB), so a
county-wide query does not transfer reliably in pages of 1,000.
**Decision (Bernard, F4, 2026-09-25).** The S14 query (`sources.S14.options`) excludes
`ZONE_SUBTY = 'AREA OF MINIMAL FLOOD HAZARD'` (539 of 9,137 polygons in the county envelope), pages
100 features, and asks the server to generalize geometry with `maxAllowableOffset` 1e-5° (~1 m)
and 6-decimal coordinates.
**Effect.** Floodway (`ZONE_SUBTY = 'FLOODWAY'`) and SFHA (`SFHA_TF = 'T'`) polygons are all kept, so
the floodway screen and flood flag are unaffected in kind; their edges can move by up to ~1 m, which
can change the result only for a parcel touching a floodway edge by less than that. Minimal-hazard
Zone X carries no screen meaning. Franklin load: 8,327 polygons.

## ADR-0063 — Existing surface lots are not failed by new-lot rules
**Context.** Zone A's prohibition (§3359.27(C)), Prohibited zoning and design overlays govern
*establishing* a lot. A parcel already operating as a surface lot may be a legal nonconforming use
(§3359.27 exempts lots established before 15 Jan 1999; Title 33 nonconforming-use rules).
**Decision (Bernard, F4, 2026-09-25).** A parcel is an *existing surface lot* when its land-use code
is 456 and the surface check confirms it (improvement ratio < 0.25, OSM surface parking ≥ 50 %,
buildings ≤ 20 %), or OSM `parking=surface` polygons cover ≥ 50 % of it. For such parcels, zoning
Fail (including Zone A) and design-overlay results become **Review** with reason "existing surface
lot — possible legal nonconforming use; verify grandfathered status (§3359.27 pre-1999 exception /
nonconforming-use rules)", and the parcel's land use counts as eligible. Size, stall range, shape,
excluded use, floodway and slope still apply.

## ADR-0064 — S20 = city curb inventory (not meter transactions)
**Context.** SCOPE §3 lists S20 as meter/kiosk *transactions* (on-street occupancy and rates).
Columbus publishes no transactions; it publishes a maintained curb inventory by block face
(PublicService/MapServer/38, edited through 2026-09-25) with stated spaces, posted hourly rates,
hours, time limits and evening periods. The 2017 "Parking Meters" point item is stale (93 % removed).
**Decision.** S20 ingests the curb inventory, filtered to active metered block faces, into
`OnStreetSegments` (`stalls_est` = stated `Spaces`, `rate_hour` = daytime `Fee1`, `metered_flag`);
hours, limits and evening rates stay in `Raw_OnStreet`. On-street occupancy is not available from
S20; if transactions become available they get their own source id. Franklin load: 1,864 block
faces, 10,715 spaces (361 without a posted rate).
