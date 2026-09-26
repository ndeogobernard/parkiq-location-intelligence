# ParkIQ — Engineering standards

The rules the codebase follows. They exist so that a partner or lender can trace any number back
to a source and a parameter, and so that a new market runs with nothing but a new config file.

## Code

* Python 3.11, type hints everywhere; `mypy --strict` clean on `parkiq/`.
* Google-style docstrings on every public function, stating the **units** of inputs and outputs.
* `ruff` for lint and format; line length 100.
* Logging via `logging.getLogger(__name__)` — no `print` in library code. Every run logs to
  `outputs/<market>/<run_id>/logs/<run_id>.log`.
* Library functions are pure where possible: (Geo)DataFrames + resolved config in, frames out. I/O
  lives in `store.py` and the runner.
* The CLI and the ArcGIS toolbox contain no analysis logic. **No `arcpy` import outside
  `toolbox/` and `arcgis/`.**
* Randomness only through a seeded `numpy.random.Generator`; the seed is recorded in `ScoreRuns`.
* Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`); one commit per milestone.

## Data and configuration

* **No hard-coded thresholds, rates, weights, costs or distances.** Every assumption lives in
  `configs/` or `markets/` with a `provenance:` entry (SCOPE / VERIFY / SET / DECIDE + source).
  Physical unit conversions (`parkiq/units.py`) are the only constants in code.
* Every config value is read through the pydantic models in `parkiq/config.py`. Unknown keys are
  errors.
* **No silent defaults or fallbacks.** A missing parameter is `null` and blocks the step that
  needs it; `check-config` says which. A fallback source (e.g. county parcels instead of Regrid)
  is logged and recorded in `params.yaml` and `DataSourceRegistry`.
* **No weight renormalization** when a criterion lacks data: it scores the configured constant and
  the run says so.
* **No fabricated sources, rates, costs, endpoints or API behaviour.** Unconfirmed items are tagged
  `[VERIFY]` and listed in `docs/VERIFY.md`.
* **No synthetic data standing in for licensed sources** (Regrid, parking apps, foot traffic,
  CoStar/LoopNet/Crexi, RSMeans, ITE/ULI, STR). A disabled source takes the "not configured" path.
  Synthetic data exists only in `tests/fixtures/`, labelled `SYNTHETIC — NOT REAL DATA`.
* **No scraping** of any site unless its terms are confirmed in `docs/VERIFY.md`.
* Naming: layers `PascalCase` (SCOPE §4.2); fields `snake_case` with unit suffixes (`_sqft`,
  `_ft`, `_m`, `_usd`, `_pct`); every layer carries `source_id`, `run_id`, `load_ts`.
* CRS: store/interchange EPSG:4326; analyze in the market `analysis_crs`; web EPSG:3857. Reproject
  on ingest and record the transformation.

## Runs

* Every step is idempotent per `run_id` and resumable from `run_log.json` input hashes.
* Every run writes `params.yaml` (fully resolved config), `data_sources.csv` and `run_log.json`.
* QA failures at error level stop the step; results are always in `QAQC_Log`.

## Finance model

* Tests accompany every formula. Python and the generated Excel workbook must agree to the dollar;
  the test recalculates the workbook independently.
* Excel formula cells never contain cached Python results (that would make the parity test
  circular).

## Repository hygiene

* Never commit data, caches, `outputs/`, `.aprx` workspaces or credentials. API keys come from
  environment variables named in the market config (e.g. `CENSUS_API_KEY`).
* No notebooks are required for any step.
* Scope changes (new criteria, dayparts or outputs) need an ADR in `docs/DECISIONS.md` first.

## Pre-push check
Before every push run `bash scripts/prepush.sh` (installed as the git `pre-push` hook). It runs the
CI gates — `ruff check`, `ruff format --check`, `mypy --strict parkiq`,
`pytest -m "not network and not arcpy"` — checks each exit code explicitly and never pipes output
through `tail`/`head`, so a failing gate cannot be hidden. Any failure exits 1 and blocks the push.
