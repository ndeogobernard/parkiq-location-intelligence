# ParkIQ SQL

Signature queries from SCOPE Appendix D, run in SQLite (or DuckDB) against a run GeoPackage.
`parkiq sql-check` runs them together with the SQL validation generated from
[`schema/schema.yaml`](../../schema/schema.yaml) (domains, required fields, unique keys,
relationship orphans) and writes every statement with its result to `sql_checks.sql` in the run
folder.

| File | What it returns |
|---|---|
| `hot_zone_hexes.sql` | hexagons short of parking on a weekday daytime and in an evening or at an event |
| `shortlist_returns.sql` | the ten best candidates by 10-year IRR with their rank in each scenario (after M6) |
