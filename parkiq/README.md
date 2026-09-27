# ParkIQ Location Intelligence Pipeline

Part of **ParkIQ: A Parking Lot Site Selection Location Intelligence Analysis**.

This folder is the Python pipeline behind the analysis. For Franklin County, Ohio, it ingests and
checks 20 public datasets, models parking demand and supply on the walking network for five times
of the week, and screens all 492,935 parcels down to ranked candidate sites for a paid surface
lot. The same code runs any US county from a market file.

## What each step does

| Step | Module | Result (Franklin County run) |
|---|---|---|
| `schema` | `schema_step.py`, `schema_build.py` | empty GeoPackage with every layer, domain and relationship from `schema/schema.yaml` |
| `setup` | `setup.py`, `network.py` | county boundary, study area, 16,069-cell H3 grid, walking network, slope raster |
| `ingest` | `ingest/` (one adapter per source) | 20 sources loaded, each with a registry row: vintage, licence, CRS, row count |
| `qaqc` | `qaqc.py` | 114 logged checks, 0 error-level failures |
| `demand` | `demand.py` | 10,350 demand anchors (offices, hospitals, campuses, hotels, restaurants, shops) by time of week |
| `supply` | `supply.py` | 6,418 mapped lots and garages, 1,864 metered block faces, lots estimated on 12,766 parcels without mapped parking |
| `gap` | `gap.py` | demand minus supply per hex and time of week; 6 hot zones where paid parking is within an 8-minute walk |
| `screen` | `screen.py` | every parcel screened on location, land use, zoning, size, stalls, shape, frontage, flood, slope and ownership |
| `walksheds` | `screen.py` | 3, 5 and 8-minute walk-shed polygons per candidate |
| `criteria`, `suitability`, `sensitivity` | `score.py` | ten criteria, three weighting scenarios, rank stability over 1,000 random weightings |

Allocation of demand and supply to hexes runs on the street network (`allocation.py`): each
source spreads over the hexes it can reach in 3, 5 and 8 minutes on foot, and the totals are
conserved.

## Run it

```powershell
. C:\GIS\ParkIQ\scripts\parkiq-env.ps1
parkiq check-config --market markets\franklin_oh.yaml
parkiq run --market markets\franklin_oh.yaml --steps schema,setup,ingest,qaqc
parkiq run --market markets\franklin_oh.yaml --steps demand,supply,gap,screen,walksheds,criteria,suitability,sensitivity --run-id <run_id>
parkiq export-gdb --market markets\franklin_oh.yaml --run-id <run_id>
parkiq dashboard --market markets\franklin_oh.yaml --run-id <run_id> --out dashboard.html
```

Each run writes one GeoPackage plus reports to `outputs/<market>/<run_id>/`. A step refuses to run
when an upstream step has not finished or a value it needs is still open; `check-config` lists
which. The full sequence with expected outputs is in [`docs/REPLICATION.md`](../docs/REPLICATION.md).

## In ArcGIS Pro

[`toolbox/ParkIQ.pyt`](../toolbox/ParkIQ.pyt) adds four tools to Pro: Check Market
Configuration, Run Pipeline Steps, Export File Geodatabase and Build Portfolio Report. They check
their inputs in Pro, then run the same commands in the ParkIQ Python environment and show its
messages. `scripts\refresh-aprx.ps1` builds a Pro project with one map per run.

## Quality gates

`scripts/prepush.sh` runs lint, format, type checks, the project text rules and the test suite
(a synthetic fixture market) before every push; GitHub Actions runs the same checks.
