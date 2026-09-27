# ParkIQ: A Parking Lot Site Selection Location Intelligence Analysis

ParkIQ finds parcels in Franklin County, Ohio, where a new **paid surface parking lot** would fill
and pay. It models parking demand and supply on a walking network for five times of the week,
finds where paid parking is short, screens every parcel against zoning, size, shape, access and
ownership rules, and ranks the remaining sites under three weighting scenarios. Buy and ground
lease underwriting follows once the partners set the finance assumptions.

**Results so far (Franklin County run of September 2026):** 20 public datasets ingested and
checked; 492,935 parcels screened; 10,350 demand anchors and 6,418 mapped parking facilities plus
1,864 metered block faces allocated on the walking network; 6 paid-market hot zones; 48 candidate
lot sites ranked (rates, venues and planned projects are still neutral, so ranks can change).

| Start here | For |
|---|---|
| [`parkiq/`](parkiq/README.md) | the pipeline: steps, commands, ArcGIS Pro toolbox |
| [`docs/analysis/`](docs/analysis/README.md) | the site selection analysis and its results |
| [`schema/`](schema/README.md) | the data model (GeoPackage and file geodatabase) |
| [`docs/maps/`](docs/maps/README.md) | the map series and map standard |
| [`docs/webapp/`](docs/webapp/README.md) | the web app and the offline dashboard |
| [`docs/REPLICATION.md`](docs/REPLICATION.md) | reproducing the Franklin County run step by step |

* Spec: [`docs/SCOPE.md`](docs/SCOPE.md) · architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
  engineering standards: [`docs/ENGINEERING.md`](docs/ENGINEERING.md) ·
  manual method: [`docs/MANUAL_METHODOLOGY.md`](docs/MANUAL_METHODOLOGY.md)
* Decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md) · open confirmations: [`docs/VERIFY.md`](docs/VERIFY.md)
* Pilot market: Franklin County, OH ([`markets/franklin_oh.yaml`](markets/franklin_oh.yaml))

**Status:** milestones M1 to M5 built (setup, ingest and QA, demand, supply, gap and hot zones,
screen, walk sheds, criteria, scoring and sensitivity); M6 underwriting waits for partner
inputs, and the rate criterion waits for the field rate survey.

## Install (Windows)

```powershell
git clone https://github.com/ndeogobernard/parkiq-location-intelligence.git C:\GIS\ParkIQ

# one-time: create the env with ArcGIS Pro's conda (arcgispro-py3 is not touched)
$env:CONDA_SSL_VERIFY = "truststore"      # only if your network re-signs HTTPS: use the Windows cert store
& "C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\conda.exe" env create -p C:\GIS\envs\parkiq -f C:\GIS\ParkIQ\environment.yml

# every session: activate (clean PATH: see ADR-0052), then install the package once
. C:\GIS\ParkIQ\scripts\parkiq-env.ps1
pip install -e "C:\GIS\ParkIQ[dev]" --no-deps
```

`parkiq-env.ps1` activates the env with a clean PATH, so third-party DLLs elsewhere on PATH cannot
shadow GDAL/rasterio's (ADR-0052). It changes the current window only.

## Development

Before every push run `bash scripts/prepush.sh`: lint, format, type checks, the project text
rules and the offline test suite (the synthetic fixture market), each checked by exit code.

## Commands

```powershell
parkiq check-config --market markets\franklin_oh.yaml --report franklin_params.csv
parkiq run --market tests\fixtures\fixture_market\fixture.yaml --steps all
parkiq run --market markets\franklin_oh.yaml --steps schema,setup
parkiq run --market markets\franklin_oh.yaml --steps ingest --run-id <run_id>            # continue a run
parkiq run --market markets\franklin_oh.yaml --steps ingest --sources S06 --run-id <run_id>
parkiq run --market markets\franklin_oh.yaml --steps setup --run-id <run_id> --force
pytest                    # offline, fixture market, ~1 min
pytest -m network         # live endpoints (opt-in)
ruff check . ; ruff format --check . ; mypy
```

Steps, in order: `schema, setup, ingest, qaqc, demand, supply, gap, screen, walksheds, criteria,
suitability, sensitivity, finance, shortlist, package`. A step refuses to run if an upstream step
has not succeeded, or if a parameter it needs is still `null` (DECIDE). `check-config` lists which.

## What a run writes

`outputs/<market>/<run_id>/` (run_id = `YYYYMMDD_HHMM_<market>_<scenario>`):

| File | Contents |
|---|---|
| `ParkIQ_<market>.gpkg` | every layer and table (SCOPE §4); `Raw_*` snapshots in EPSG:4326; `_ParkIQ_Layers` registry |
| `rasters/Slope_pct.tif` | percent slope (Horn), analysis CRS |
| `params.yaml` | the fully resolved configuration used |
| `data_sources.csv` | DataSourceRegistry export: source, vintage, license, CRS, transformation |
| `run_log.json` | per step: status, input hash, summary; used to resume |
| `logs/<run_id>.log` | full log |

Downloads are cached once per market outside the repository, in `../ParkIQ_cache/<market>/`
(override with `PARKIQ_CACHE_ROOT`; ADR-0056), and never re-downloaded per run.

## ArcGIS Pro workspace

`scripts\refresh-aprx.ps1` (close the project in Pro first) builds
`arcgis\ParkIQ_Workspace.aprx`: one map per run (`<market> | <run_id>`) with layers grouped by
feature dataset (Results, Analysis, Supply, Demand, Cadastral, Reference, Raw), the run's
attribute tables (QAQC_Log, DataSourceRegistry, ScoreRuns, …), rasters, the step summaries in each
map's metadata, folder connections to the repo, outputs, docs, configs and scripts, and a scratch
geodatabase for manual work. Maps you add yourself are kept; generated maps are rebuilt. Use
`-All` for every run and `-Open` to launch Pro afterwards. The `.aprx` is local only (not committed).

## Configuration

| File | Holds |
|---|---|
| `markets/<slug>.yaml` | one market: boundary, CRS, screen/demand/supply parameters, finance overrides, sources |
| `configs/weights.yaml` | scenario weights (SCOPE App. B) |
| `configs/parking_rates.yaml` | generation rates (SCOPE App. C), every row `[VERIFY]` |
| `configs/finance_defaults.yaml` | finance defaults; DECIDE items `null` |
| `configs/criteria.yaml` | C01–C10 definitions and normalization |
| `configs/sources.yaml` | source catalogue: providers, licences, URL templates, `[VERIFY]` flags |
| `schema/schema.yaml` | the data model (layers, fields, domains) |

Every numeric parameter carries a `provenance:` entry (`SCOPE` / `VERIFY` / `SET` / `DECIDE` +
source), mirroring the admin workbook's Parameters sheet. Unknown keys are errors.

A source you downloaded by hand is used via `sources.<id>.path` in the market file (paths are
relative to the market file). Licensed sources stay off unless their `data_licenses` flag is on;
when off, they are registered as "not configured" and produce no rows, never synthetic stand-ins.

## New-market onboarding (checklist grows each milestone)

1. Copy `markets/_template.yaml` → `markets/<slug>.yaml`; set boundary, `analysis_crs`, `units`.
2. `parkiq check-config --market markets/<slug>.yaml` until it reports OK; review BLOCKED steps.
3. `parkiq run --market markets/<slug>.yaml --steps schema,setup` → check `HexGrid`, `WalkEdges`.
4. Download/point the sources (`sources:` block), then `--steps ingest,qaqc --run-id <run_id>`.

## Repository layout

SCOPE §6.2 plus the additions in ARCHITECTURE §1 / ADR-0005, -0006, -0051: `parkiq/` (library, no
`arcpy`), `parkiq/ingest/` (one adapter per source), `configs/`, `markets/`, `schema/`,
`tests/` (fixture market is **SYNTHETIC: NOT REAL DATA**), `arcgis/` (ArcPy only: workspace
builder, file geodatabase export; `manual/` holds the Session-1 scripts), `toolbox/` (ArcGIS Pro
Python toolbox), `templates/` (M6 to M7), `docs/`.

## Licence

Code: MIT © 2026 Bernard Issifu (see [`LICENSE`](LICENSE)). Data retains its source licences
(e.g. OpenStreetMap under ODbL, "© OpenStreetMap contributors" on every map that uses it).
