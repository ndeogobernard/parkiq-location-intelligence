# ParkIQ — Open confirmations ([VERIFY] register)

Each item is a value, endpoint, format or term of use that has not been confirmed against a live
source. It stays tagged `[VERIFY]` in configs and in the `DataSourceRegistry.license` column until
closed. `parkiq check-config` prints the ones that affect a given market.

To close an item: confirm it, update the config value or `source:` text, set its provenance status to `SET`,
and move it to **Closed** with date and citation.

Status: **Open** unless noted. "Owner" = who can close it (A = analyst, P = partners).

## From SCOPE

| ID | Item | Where | Owner |
|---|---|---|---|
| V-01 | Licence for `parking_generation_source` (ITE Parking Generation / ULI Shared Parking), or which published summaries may be cited | `markets/*.yaml demand.parking_generation_source` | A/P |
| V-02 | `construction_cost_per_stall_usd` 6,500 — regional quote / cost index (Columbus-area paving contractor, per workbook) | `configs/finance_defaults.yaml` | A |
| V-03 | SpotHero / ParkWhiz / ParkMobile access — API/partner terms. **No scraping** without written confirmation | S07 (M2) | P |
| V-04 | Generation rates in general (cite ITE/ULI) — see V-05…V-12 | `configs/parking_rates.yaml` | A |
| V-05 | office 0.80/0.05/0.05/0.02/0.00 per employee — edition, LU 701, per-employee daypart peaks | rates | A |
| V-06 | medical per bed — source | rates | A |
| V-07 | university per student — source | rates | A |
| V-08 | hotel per room — source | rates | A |
| V-09 | restaurant/bar per 1,000 sqft — source | rates | A |
| V-10 | retail per 1,000 sqft — source | rates | A |
| V-11 | venue 0.33 = 0.85 drive share ÷ 2.6 persons/car — both inputs | rates | A |
| V-12 | residential per unit without off-street parking — source and unit definition (ADR-0015) | rates | A |

## Data terms, endpoints and defaults

| ID | Item | Where | Owner |
|---|---|---|---|
| V-13 | Overture release id and S3 path; whether Places has a parking category; current Places taxonomy fields (`categories.primary`) | S02, S03a | A |
| V-14 | LODES version (LODES8) and latest year for Ohio; WAC `CNS01–20` → sector mapping; crosswalk columns `tabblk2020, blklatdd, blklondd` | S04 | A |
| V-15 | **Finding 2026-09-24: the Census Data API now requires a key** (unkeyed calls redirect to `missing_key.html`) — set `CENSUS_API_KEY`. Also: ACS vintage and variable IDs (B01003_001E, B08301_001E/002E, B25024_001E/006E–009E, B25044_001E/003E/010E); API key policy; a workplace-based mode-share source (CTPP / ACS place-of-work) | S05 | A |
| V-16 | COTA GTFS current URL via Mobility Database (token requirement) | S09 | A |
| V-17 | Ticketmaster Discovery API terms (analytics/storage) and key | S10 (M2) | A/P |
| V-18 | Hospitals with beds: HIFLD Open availability (believed changed in 2025, unconfirmed) or CMS provider files; bed field | S12a | A |
| V-19 | IPEDS HD/EFFY file names by year; enrollment field (`EFYTOTLT`) and all-students filter (`EFFYLEV = 1`); main-campus location vs. satellites | S12b | A |
| V-20 | ODOT TIMS traffic-count layer URL (workbook) — layer index, AADT and year field names | S13 | A |
| V-21 | FEMA NFHL service layer (`…/NFHL/MapServer/28`) and floodway encoding (`ZONE_SUBTY` contains "FLOODWAY"; `SFHA_TF = 'T'`) | S14 | A |
| V-22 | EPA FRS / ACRES download or service; program field and which programs count as brownfield | S15 | A |
| V-23 | USGS TNM Access API product search (`/api/v1/products`, dataset name "National Elevation Dataset (NED) 1/3 arc-second") and tile download volume for Franklin (~4 × 1° tiles) | S18 | A |
| V-24 | Regrid API/bulk format, fields, zoning add-on, storage/derivation terms | S01 Regrid (M2) | P |
| V-25 | Placer.ai / Advan delivery format and terms | S19 (M2) | P |
| V-26 | CoStar / LoopNet / Crexi terms (many prohibit scraping/redistribution) | S16 (M2) | P |
| V-27 | RSMeans city cost index licence | S17 (M6) | P |
| V-28 | Franklin County Auditor parcel + CAMA sources: which file carries land/improvement values and the land-use code; join key; field names (run `arcgis/manual/02_inspect_layer.py` and paste the profile) | S01 | A |
| V-29 | Basemap terms for Esri Light Gray Canvas outside ArcGIS (matplotlib maps) | M7 | A |
| V-30 | Finance placeholders from SCOPE §2.1 (assessed_to_market_ratio 1.20, soft 0.15, opex 450, tax 0.012, discount 0.10, caps, cap rate 0.075, discount rate 0.12) — Franklin effective commercial tax rate by district (Auditor) | finance | A |
| V-31 | Walking speed 1.3 m/s; transit factor 0.85 within 400 m; high-frequency headway threshold | market | A |
| V-32 | `formulas` package IRR/NPV support for the parity test | M6 | dev |
| V-33 | TIGER/Line URL pattern and year (`TIGER{year}/COUNTY/tl_{year}_us_county.zip`; PLACE per state) | S00 | A |
| V-34 | Columbus open-data layers (zoning, meters, permits) — currency (the meters item dates from 2017, per workbook) | S20–S23 (M2) | A |

## Closed

| ID | Item | Closed | Evidence |
|---|---|---|---|
| — | — | — | — |
