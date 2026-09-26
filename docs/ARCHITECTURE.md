# ParkIQ: Architecture

How the toolkit is built. The *what* and *why* are in [`SCOPE.md`](SCOPE.md); method choices in
[`DECISIONS.md`](DECISIONS.md); coding rules in [`ENGINEERING.md`](ENGINEERING.md).

Contents: 1 Layers · 2 Run lifecycle · 3 Storage · 4 Source adapters · 5 Fixture market ·
6 Testing · 7 Milestones · 8 SCOPE traceability

---

## 1. Layers

The analytical core is a plain Python library with **no ArcPy import anywhere**. Thin front ends
sit on top and contain no analysis logic.

| Layer | Location | Responsibility |
|---|---|---|
| Library | `parkiq/*.py`, `parkiq/ingest/` | All analysis; functions take/return (Geo)DataFrames plus a run context |
| Runner | `parkiq/runner.py` | Step registry, dependency order, resume, run folder, `run_log.json` |
| CLI | `parkiq/cli.py` (Typer) | Argument parsing → runner calls |
| ArcGIS | `toolbox/ParkIQ.pyt`, `arcgis/` | 17 toolbox tools that call the CLI (ADR-0016); `.gdb` export, cartography, the local workspace `.aprx` |

Modules added beyond SCOPE §6.2: `config.py` (pydantic models, merge, validation), `runner.py`,
`store.py` (GeoPackage I/O), `schema.py` + `schema_step.py` (data model, BuildSchema), `qaqc.py`,
`units.py`, `geo_codes.py`, `finance_excel.py` (M6), and ingest adapters for sources SCOPE §3 lists
but §6.2 omits (`county_parcels`, `hospitals`, `ipeds`, `aadt`, `foot_traffic`,
`manual_observations`). Nothing in §6.2 is renamed or removed.

## 2. Run lifecycle

`run_id = YYYYMMDD_HHMM_<market>_<scenario>` (SCOPE §6.5). The first invocation creates
`outputs/<market>/<run_id>/`; pass `--run-id` to continue. Each step:

1. refuses to run if an upstream step has not succeeded in this run, or if a config value it needs
   is still `null` (DECIDE; `parkiq.config.STEP_REQUIREMENTS`);
2. computes an **input hash**: the config sections it reads, upstream step hashes, code version
   (package version + git commit) and, for setup/ingest, fingerprints of local input files, and
   skips if `run_log.json` already records success with the same hash (unless `--force`);
3. rewrites its own outputs (idempotent, §3);
4. records itself in `run_log.json` and `ScoreRuns`, refreshes `params.yaml` (the fully resolved
   config) and `data_sources.csv`, and marks downstream steps from an earlier pass `stale`.

Downloads are cached per market in `outputs/<market>/_cache/<source_id>/<vintage>/`; each run's
GeoPackage keeps an immutable `Raw_*` snapshot of what it used (SCOPE §4.5).

## 3. Storage: the SCOPE geodatabase design on GeoPackage

One self-contained GeoPackage per run (ADR-0010). A run's GeoPackage only ever holds that run, so a
spatial layer is rewritten whole; shared tables (`QAQC_Log`, `DataSourceRegistry`, `ScoreRuns`, …)
delete `WHERE run_id = ? AND <key>` before appending. Every write is validated against
`schema/schema.yaml`: field set, types, nullability, uniqueness, coded/range domains, CRS, and the
lineage fields `source_id, run_id, load_ts`.

| Geodatabase concept (SCOPE §4) | GeoPackage implementation | `.gdb` export (ArcPy, optional) |
|---|---|---|
| Feature dataset | `_ParkIQ_Layers` registry (layer, feature dataset, geometry, CRS); PascalCase names as SCOPE §4.2 | Real feature datasets |
| Coded/range domains | Enforced on write from `schema.yaml`; GeoPackage schema-extension constraints (M2); re-checked by RunQAQC | `CreateDomain` |
| Subtypes | `subtype` field + mapping in `schema.yaml` (M2) | `SetSubtypeField` |
| Relationship classes | GeoPackage Related Tables extension (M2) | `CreateRelationshipClass` |
| Topology | RunQAQC geometric checks (e.g. HexGrid no overlap / no gap) | Optional `CreateTopology` |
| Attribute rules | Computed on write (`lot_sqft`, `improvement_value_ratio`) + range checks | Attribute rules |
| Rasters | GeoTIFF in `rasters/`, registered; values sampled to hexes/parcels (ADR-0012) | Copied as rasters |
| Hex "polygon/table" outputs | Tables keyed `(hex_id, daypart, run_id)` + spatial views on `HexGrid` | Tables + joined FCs |
| ISO 19139 metadata | Generated XML per layer (M8) | `arcpy.metadata` |

CRS: storage/interchange EPSG:4326 (`Raw_*`), analysis in the market `analysis_crs`, web delivery
EPSG:3857 (SCOPE §2.3).

## 4. Source adapters

```text
class SourceAdapter:
    source_id: str                # "S01" … "S24" (S03a/S03b, S12a/S12b split, ADR-0051)
    license_flag: str | None      # key in market.data_licenses; None for free sources
    def is_enabled(ctx) -> (bool, reason)
    def fetch(ctx)        -> local file(s)        # market `path` override, else cached download
    def standardize(raw, ctx) -> Standardized     # target-schema frames, analysis CRS, clipped
```

The ingest step writes each adapter's `Raw_*` snapshot and target layers and one
`DataSourceRegistry` row (provider, endpoint, vintage, licence, native CRS, transformation). Layers
fed by several sources (`Places`) are merged with a per-row `source_id`. A **disabled or unlicensed
adapter** writes a registry row with status `not configured`, logs a WARNING naming the downstream
effect, and writes no rows, it is never replaced with synthetic data. Endpoints, licences, tag
queries and URL templates live in `configs/sources.yaml`; unconfirmed ones carry `verify: true` and
appear in [`VERIFY.md`](VERIFY.md).

| ID | Adapter | Access |
|---|---|---|
| S00 | TIGER boundary (in `setup.py`) | free |
| S01 | `county_parcels.py` (Regrid, licensed, in M2) | free fallback / licensed |
| S02, S03a | `overture.py` (DuckDB over the Overture S3 release) | free |
| S03b, S06 | `osm.py` (OSMnx features) | free |
| S04 | `lodes.py` (WAC + crosswalk block points) | free |
| S05 | `acs.py` (Census API, key required, + TIGER block groups) | free |
| S08 | `network.py` (OSMnx walk graph) | free |
| S09 | `gtfs.py` (peak departures, headway, high-frequency flag) | free |
| S10 | `events.py` (venue seats / events per year) | own data (+ Ticketmaster, M2) |
| S12a, S12b | `hospitals.py`, `ipeds.py` | free |
| S13, S14 | `aadt.py`, `fema.py` (ArcGIS REST, paged, bbox) | free |
| S15 | `epa.py` | free |
| S18 | `dem.py` (TNM Access API) | free |
| S07, S16, S19, S20–S24 | listings, foot traffic, city open data, manual observations (M2) | licensed / optional |

## 5. Fixture market

`tests/fixtures/fixture_market/`, **SYNTHETIC: NOT REAL DATA**, generated by a seeded script and
labelled inside every file. A 1.5 × 1.5 km square placed in Lake Erie (UTM 17N) so it cannot be
mistaken for a real place. Each file mimics its real source's *format* (GraphML from OSMnx,
Overture GeoParquet structs, LODES CSVs, a GTFS zip, NAD83 DEM, NFHL fields…) and deliberately
exercises branches: out-of-area records, a multipart parcel, unmatched land-use codes, a parent
station, a weekend trip, a floodway, a brownfield, an ACS sentinel value. Finance inputs for the
fixture live in its own market file, so shared defaults stay `[VERIFY]` / null. The full pipeline
and tests run offline in about a minute.

## 6. Testing

* `pytest`: unit + integration on the fixture (offline). Markers: `network` (live endpoints,
  opt-in), `arcpy` (only inside ArcGIS Pro's Python).
* Required coverage (SCOPE §6.5): walk-shed allocation, capacity estimation,
  normalization/weighting/ranking, sensitivity, every finance formula, and **Python ↔ Excel
  parity**, the generated workbook is recalculated independently and compared cell by cell.
* Determinism: seeded randomness, sorted writes; re-running a step with the same inputs gives the
  same tables.
* `ruff check`, `ruff format --check`, `mypy --strict` on `parkiq/`.

## 7. Milestones

Each milestone ends with tests, a fixture run, a pilot check where possible, and one commit.

| # | Scope (SCOPE §11) | Status |
|---|---|---|
| M1 | Config schema; SetupMarket; free-source ingest; H3 grid; walk network | **Done**: Franklin boundary, grid (16,069 hexes) and walk network (598k edges) built live |
| M2 | Full BuildSchema, schema-diff, ERD, data dictionary; Regrid/listings/city/manual adapters | next |
| M3 | Supply inventory, capacity estimation, rate surface | |
| M4 | Demand model, allocation, gap, hot zones | |
| M5 | Candidate screen, walk sheds, criteria, scenarios, sensitivity | |
| M6 | Financial model (Python + live-formula Excel), shortlist | |
| M7 | Maps, map series, dashboard, memo, StoryMap outline, toolbox | |
| M8 | Pilot validation and calibration, acceptance tests, onboarding | |

## 8. SCOPE traceability

| SCOPE § | Implemented in |
|---|---|
| 2.1–2.3 Market config, study area, CRS | `markets/*.yaml`, `config.py`, `setup.py`, `units.py` |
| 3 Sources | `parkiq/ingest/*`, `configs/sources.yaml` |
| 4 Data model | `schema/schema.yaml`, `schema.py`, `store.py`, `qaqc.py` |
| 5.1 Setup | `setup.py`, `network.py` |
| 5.2–5.4 Demand, supply, gap | `demand.py`, `supply.py`, `gap.py` (M3–M4) |
| 5.5–5.7 Screen, network, scoring | `screen.py`, `network.py`, `score.py` (M5) |
| 5.8 Finance | `finance.py`, `finance_excel.py` (M6) |
| 5.9 Validation | `validate.py` (M8) |
| 6 Automation | `runner.py`, `cli.py`, `toolbox/` |
| 7–9 Maps, dashboard, StoryMap, memo | `maps.py`, `dashboard.py`, `report.py`, `arcgis/` (M7) |
| 10 QA/QC | `qaqc.py` + checks in each step |
| App. B, C | `configs/weights.yaml`, `configs/parking_rates.yaml` (verbatim) |
