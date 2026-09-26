# ParkIQ: Location Intelligence for Parking Site Selection

A repeatable, config-driven toolkit that finds developable parcels where a **paid surface parking
lot** fills across dayparts and pays. It models demand by daypart at walk-shed resolution,
inventories supply and rates, finds unmet multi-daypart demand, screens and scores parcels,
underwrites each one (buy and ground lease) and exports an investment package.

* Spec: [`docs/SCOPE.md`](docs/SCOPE.md) (source of truth) · architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
  engineering standards: [`docs/ENGINEERING.md`](docs/ENGINEERING.md) ·
  manual method: [`docs/MANUAL_METHODOLOGY.md`](docs/MANUAL_METHODOLOGY.md)
* Decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md) · open confirmations: [`docs/VERIFY.md`](docs/VERIFY.md)
* Pilot market: Franklin County, OH ([`markets/franklin_oh.yaml`](markets/franklin_oh.yaml))

**Status:** M1 of 8. Built: config, schema v0, SetupMarket (boundary, study area, H3 grid, walk
network, slope), free-source ingest, QA. Everything from `demand` onward is a later milestone.

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

**Tools:** _TODO_

Lint, format and type checks run with `ruff check .`, `ruff format --check .` and `mypy`; the
offline test suite (`pytest`) runs the synthetic fixture market in about a minute.

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
`tests/` (fixture market is **SYNTHETIC: NOT REAL DATA**), `arcgis/` (ArcPy only; `manual/` holds
the Session-1 scripts), `toolbox/` (M7), `templates/` (M6–M7), `docs/`.

## Licence

Code: MIT © 2026 Bernard Issifu (see [`LICENSE`](LICENSE)). Data retains its source licences
(e.g. OpenStreetMap under ODbL, "© OpenStreetMap contributors" on every map that uses it).
