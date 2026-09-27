# Reproducing the Franklin County run

Part of **ParkIQ: A Parking Lot Site Selection Location Intelligence Analysis**.

This guide rebuilds the Franklin County, Ohio, analysis from public data on a Windows machine.
The reference run is `20260925_2217_franklin_oh_Balanced` (analysis as of September 2026). Live
sources (OpenStreetMap, Overture, City of Columbus services) change over time, so a new run will
differ slightly; the checks below say what to expect.

## 1. Prerequisites

* Windows 10 or 11 with ArcGIS Pro 3.x installed (its conda is used to create the environment;
  Pro itself is needed only for the file geodatabase export and the toolbox).
* About 10 GB free (the Franklin cache is about 4 GB and one run about 3.6 GB).
* A free Census Data API key in the user environment variable `CENSUS_API_KEY`. `CTPP_API_KEY`
  is only needed to rebuild the committed CTPP table
  (`markets/franklin_oh/workplace_drive_share_tract.csv`). Keys are read from the environment,
  never stored or logged (ADR-0057).

## 2. Install

```powershell
git clone https://github.com/ndeogobernard/parkiq-location-intelligence.git C:\GIS\ParkIQ
& "C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\conda.exe" env create -p C:\GIS\envs\parkiq -f C:\GIS\ParkIQ\environment.yml
. C:\GIS\ParkIQ\scripts\parkiq-env.ps1
pip install -e "C:\GIS\ParkIQ[dev]" --no-deps
```

`parkiq-env.ps1` activates the environment with a clean PATH and loads the API keys from the user
environment into the current window. Set `$env:CONDA_SSL_VERIFY = "truststore"` first if your
network re-signs HTTPS traffic.

## 3. Files you download by hand

Downloads go to the cache `C:\GIS\ParkIQ_cache\franklin_oh\` (next to the repository; override
with `PARKIQ_CACHE_ROOT`). The market file `markets/franklin_oh.yaml` points to these paths; edit
them if your cache is elsewhere.

| Source | File (market file key) | Where |
|---|---|---|
| S01 parcels | `S01/2026-09-23/20260923_Parcel_Polygons/TAXPARCEL_CONDOUNITSTACK_LGIM.shp` (`sources.S01.path`) | Franklin County Auditor GIS downloads, parcel polygons shapefile |
| S01 tax districts | `S01/2026-09-23/20260923_TaxDistricts/LOCALTAXDISTRICT.shp` | Franklin County Auditor GIS downloads, tax districts shapefile |
| Census tracts 2021 (CTPP geography) | `demand/tl_2021_39_tract.zip` (`demand.workplace_places_path`) | Census TIGER/Line 2021, tracts, Ohio |
| Census places 2024 | `demand/tl_2024_39_place.zip` (`demand.jurisdiction_places_path`) | Census TIGER/Line 2024, places, Ohio |
| S23c Downtown parking zones | `S23c/S23c_parking_zones.gpkg` | digitized from Columbus City Code 3359.27 Map 2; not distributed. Without it, Downtown sites near Zone A/B route to Review. |

Everything else (boundary, OpenStreetMap parking, places and walking network, Overture
buildings, LODES jobs, ACS, COTA GTFS, CMS hospitals list in `markets/franklin_oh/`, IPEDS, ODOT
traffic counts, FEMA flood, EPA sites, 3DEP elevation, City of Columbus meters and zoning) is
downloaded by the pipeline on first use and cached.

## 4. Check the configuration

```powershell
parkiq check-config --market markets\franklin_oh.yaml
```

Expected: "OK: Franklin County, OH (franklin_oh), EPSG:3735", every step up to `sensitivity`
ready, and `finance` BLOCKED (its assumptions are still open).

## 5. Run

```powershell
parkiq run --market markets\franklin_oh.yaml --steps schema,setup
parkiq run --market markets\franklin_oh.yaml --steps ingest,qaqc --run-id <run_id>
parkiq run --market markets\franklin_oh.yaml --steps demand,supply,gap --run-id <run_id>
parkiq run --market markets\franklin_oh.yaml --steps screen,walksheds,criteria,suitability,sensitivity --run-id <run_id>
```

The first command prints the new run id (`YYYYMMDD_HHMM_franklin_oh_Balanced`); pass it to the
others. A step that has already finished with the same inputs is skipped; add `--force` to rerun
it. `setup` downloads the county walking network and elevation once, and `ingest` downloads every
source once, so the first run takes several hours; later runs reuse the cache.

## 6. What to expect

| Check | Reference run | Where to look |
|---|---|---|
| H3 cells (resolution 9) | 16,069 | layer `HexGrid` |
| Parcels | 492,935 | layer `Parcels` |
| Sources loaded | 20 (5 recorded as not configured) | `data_sources.csv` |
| QA checks | 114, 0 error-level failures | table `QAQC_Log` |
| Demand anchors | 10,350 | layer `DemandAnchors`, `demand_report.json` |
| Weekday-day demand | 382,785 stalls | `demand_report.json` |
| Mapped lots and garages | 6,418 | layer `SupplyFacilities` (plus 12,766 parcel estimates) |
| Metered block faces | 1,864 | layer `OnStreetSegments` |
| Paid-market hot zones | 6 (4 short by 50 stalls or more) | `gap_report.json`, layer `HotZones` |
| Candidate sites | 48 (2 Pass, 46 Review) | `screen_report.json`, layer `CandidateParcels` |
| Schema check | 0 differences | `parkiq schema-diff` (section 7) |

## 7. Outputs and extras

```powershell
parkiq schema-diff --market markets\franklin_oh.yaml --gpkg outputs\franklin_oh\<run_id>\ParkIQ_franklin_oh.gpkg
parkiq export-gdb --market markets\franklin_oh.yaml --run-id <run_id>
parkiq dashboard --market markets\franklin_oh.yaml --run-id <run_id> --out outputs\franklin_oh\<run_id>\dashboard.html
```

* Every run writes `outputs/franklin_oh/<run_id>/`: the GeoPackage, `params.yaml` (the resolved
  configuration), `data_sources.csv`, step reports (`*_report.json`), `run_log.json` and a log.
* `export-gdb` writes `ParkIQ_franklin_oh.gdb` next to the GeoPackage (needs ArcGIS Pro).
* `dashboard` writes a self-contained HTML (add `--no-public` for the version with candidates).
* In ArcGIS Pro, `toolbox\ParkIQ.pyt` runs the same steps; `scripts\refresh-aprx.ps1` builds a
  project with one map per run.

## 8. Tests

```bash
bash scripts/prepush.sh
```

Runs lint, format, type checks, the text rules and the test suite on a synthetic fixture market
(no downloads).
