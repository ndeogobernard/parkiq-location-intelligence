# ParkIQ Parking Data Model

Part of **ParkIQ: A Parking Lot Site Selection Location Intelligence Analysis**.

The data model is one file, [`schema.yaml`](schema.yaml): 31 feature classes, 13 attribute
tables, 19 raw source snapshots, 14 coded and range domains, subtypes and 11 relationship
classes. From that one file ParkIQ builds, checks and documents every run.

| Built from `schema.yaml` | Where |
|---|---|
| Empty GeoPackage for a new run (fields, types, domains as GeoPackage constraints) | `parkiq run --steps schema` |
| Validation of every write (types, nulls, unique keys, domain values) | `parkiq/schema.py` |
| Difference report between any GeoPackage and the definition | `parkiq schema-diff --gpkg <file>` |
| SQL validation in SQLite: domains, required fields, unique keys, relationship orphans, SCOPE signature queries | `parkiq sql-check` ([`docs/queries/`](../docs/queries/README.md)) |
| Entity-relationship diagram | [`docs/ERD.png`](../docs/ERD.png), [`docs/ERD.drawio`](../docs/ERD.drawio) |
| Data dictionary | [`docs/DataDictionary.md`](../docs/DataDictionary.md) |
| File geodatabase with feature datasets, domains, subtypes and relationship classes | `parkiq export-gdb` |

The Franklin County run (September 2026) matches the definition with 0 differences and passes
all 202 SQL checks; the hot-zone signature query returns exactly the 2,578 hexagons the gap step
qualified. Every SQL statement is written to `sql_checks.sql` in the run folder, so it can be rerun
in any SQLite client.

## Feature datasets

* **Reference:** market boundary, study area, H3 grid, walking network, zoning, parking zones, flood, environmental sites
* **Cadastral:** parcels, buildings
* **Demand:** demand anchors, places, jobs, block groups, transit stops, hospitals, campuses, venues
* **Supply:** parking facilities, metered block faces
* **Analysis:** hot zones, candidate parcels, walk sheds
* **Results:** site scores, financials, shortlist

Demand, supply and gap per hex and time of week are attribute tables keyed by the H3 cell id, so
each of the 16,069 hexagons is stored once and joined for mapping.

## Lineage

Every feature class carries `source_id`, `run_id` and `load_ts`. Each run keeps a source registry
(endpoint, vintage, download date, licence, native CRS, transformation, row count) and a QA log,
so any number traces back to its source and the run that produced it.

Report: [ParkIQ Parking Data Model (PDF)](https://ndeogobernard.github.io/ndeogo/documentation/parkiq-data-model-documentation.md.pdf)
