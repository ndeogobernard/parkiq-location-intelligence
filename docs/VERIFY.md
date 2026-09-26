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
| V-17 | Ticketmaster Discovery API terms (analytics/storage) and key | S10 (M2) | A/P |
| V-24 | Regrid API/bulk format, fields, zoning add-on, storage/derivation terms | S01 Regrid (M2) | P |
| V-25 | Placer.ai / Advan delivery format and terms | S19 (M2) | P |
| V-26 | CoStar / LoopNet / Crexi terms (many prohibit scraping/redistribution) | S16 (M2) | P |
| V-27 | RSMeans city cost index licence | S17 (M6) | P |
| V-28 | Franklin County Auditor parcel + CAMA sources: which file carries land/improvement values and the land-use code; join key; field names. **Profiled 2026-09-24 (extract 2026-09-23):** the parcel shapefile carries everything needed (PARCELID, CLASSCD, LNDVALUEBA/BLDVALUEBA, OWNERNME1, SITEADDRES, CVTTXCD); LNDVALUEBA = appraisal COSTLAND for 94.7% of parcels, i.e. 100% appraised value, not 35% taxable; CAMA join not needed for v1 (key differs: `010-000001` vs `010-000001-00`). Field map, land-use crosswalk and owner rules drafted — open until reviewed (F3) | S01 | A |
| V-29 | Basemap terms for Esri Light Gray Canvas outside ArcGIS (matplotlib maps) | M7 | A |
| V-30 | Finance placeholders from SCOPE §2.1 (assessed_to_market_ratio 1.20, soft 0.15, opex 450, tax 0.012, discount 0.10, caps, cap rate 0.075, discount rate 0.12) — Franklin effective commercial tax rate by district (Auditor). **Note 2026-09-25 (for M6):** Franklin `LNDVALUEBA` is already 100% appraised market value, so the 1.20 assessed-to-market placeholder likely does not apply as written. Calibrate the ratio from recent arm's-length sales, not listings: the Auditor appraisal files (Sales010/020-277/410-610.txt) carry SALEDT, PRICE, VALID ('0 - VALID') and SALETYPE ('1 - LAND ONLY'); 459 valid single-parcel land-only sales since 2021 on 3xx/4xx/vacant codes. Value unchanged until M6 | finance | A |
| V-31 | Walking speed 1.3 m/s; transit factor 0.85 within 400 m; high-frequency headway threshold | market | A |
| V-32 | `formulas` package IRR/NPV support for the parity test | M6 | dev |
| V-13b | Overture Places: whether a parking category exists; current taxonomy field (`categories.primary`) — S03a still disabled | S03a | A |
| V-35 | Downtown parking zones A/B (S23c) are DERIVED from City Code Map 2 (ADR-0061): Bernard is asking the City whether an official GIS layer exists; if so it replaces S23c. Until then DD parcels within 150 ft of the A/B line route to Review | S23c | A |
| V-36 | Hospital beds — ONE source: CMS POS Q2 2026 BED_CNT (ADR-0066). Spot-check of the five largest vs the hospitals' own figures (2026-09-26): Riverside 1,000 vs 1,059 (single campus; OK); OSU Univ. Hospitals 971 vs no per-hospital figure (medical center 1,463 staffed across 6 hospitals; new tower opened 2026-02-22; plausible); **Mount Carmel East 937 vs ~400 at the East campus** (CCN also reports Grove City, 210; ~327 unexplained) — CMS overstates the 6001 E Broad St point; Grant 645 vs 'more than 650' (OK); **Nationwide Children's 378 vs 703 licensed Columbus beds** (CMS likely excludes licensed/NICU/behavioral beds) — CMS understates. **Resolved 2026-09-26 (ADR-0066 amendment):** CCN 360035 → published campus figures East 400 / Grove City 210 (Bernard 2026-09-26); the remaining 327 beds: CMS total includes beds not at either current campus; Nationwide Children's kept at CMS 378 — licensed 703 vs CMS gap goes in the memo assumptions | S12a | A |
| V-37 | Licence of Columbus PublicService/MapServer/38 (no Hub item; sibling City items CC0) | S20 | A |
| V-38 | ODOT TIMS terms of use (copyright 'ODOT Office of Technical Services'; no terms page found) | S13 | A |
| V-42 | Arena District survey stratum is an analyst construct (downtown overlay north of W Spring St, west of N High St); Short North / University District are the SIDs (High St corridors; OSU campus garages outside) | survey | A |
| V-45 | Paid-market indicators outside the core: HZ-P0002 (Easton) rests on four OSM `fee=yes` surface lots and HZ-P0001 (east side, near Mount Carmel East) on one `fee=yes` garage. Bernard: not sure (2026-09-26) → kept, and added to round-1 survey (stratum 'Paid-signal check (V-45)'); if free, add to paid_signal_overrides.csv and re-run gap | gap | survey |
| V-46 | Benchmark gaps vs SPP 2019 (report only; calibration M8). After the attendance factor (ADR-0078): Downtown Zone A/B model 0.93 vs Capitol Square 81.6 % (+14 %), Short North 0.77 vs 60.9 % (+26 %), Arena 0.64 vs 92.5 % (−30 %), Brewery 0.35 vs 65 % (−45 %). 2019 is pre-pandemic | demand | M8 |
| V-48 | Office attendance factor 0.71 (ADR-0078) is a nationwide Placer.ai figure vs 2019; a Columbus-specific ratio vs 2019 (DCI / Placer.ai) would replace it | demand | A |

## Closed

| ID | Item | Closed | Evidence |
|---|---|---|---|
| V-43 | Workplace drive share below place level | 2026-09-26 | ADR-0073: CTPP 2017–2021 B202105 tract of work (S25), min 100 commuters |
| V-44 | Downtown demand benchmark | 2026-09-26 | City SPP 2019 (Kimley-Horn; operator data fall 2018, LPR on-street Nov 2018): off-street surveyed/peak — Arena 7,839 / 92.5 %, Capitol Square 10,582 / 81.6 %, Short North–Warehouse 7,092 / 60.9 %, Brewery–RiverSouth 2,027 / 65 %, Scioto Peninsula 917 / 22 %, East Downtown 283 / 64.7 %; on-street ≈ 40 % at system peak. Comparison → V-46 |
| V-47 | Auditor Edge-of-Pavement as parking polygons | 2026-09-26 | ADR-0074: lines only; polygonized precision 5.7 %, recall 55 % → rejected; parcel-based estimate instead |
| V-39 | Surface capacity estimate vs stated | 2026-09-26 | ADR-0067: factor 1.414 (n 356, IQR 0.979–2.000) on existing-lot area estimates; new-lot layout keeps 320/0.90; recompute from round-1 survey |
| V-40 | Non-parking lots in OSM parking | 2026-09-26 | ADR-0067: reviewable exclusion list markets/franklin_oh/supply_exclusions.csv |
| V-41 | Untagged lots private; curb-sensitive ratio | 2026-09-26 | SET, analyst choice (Bernard) |
| V-18 | Hospitals with beds | 2026-09-26 | HIFLD Open retired (404). FEMA RAPT copy of HIFLD Hospitals (`services.arcgis.com/XG15cJAlne2vxtgt/.../Hospitals_RAPT/FeatureServer/6`, data edited 2026-04-22); 32 open hospitals in the study area, 4 without beds. Bed counts differ from CMS POS — see V-36 |
| V-19 | IPEDS file names, enrollment field/filter | 2026-09-26 | HD2024/EFFY2024 latest (2025 → 404); EFYTOTLT with EFFYLEV = 1; 28 institutions (OSU main 65,036) |
| V-20 | ODOT TIMS traffic counts | 2026-09-26 | `Traffic_Count_Stations/MapServer/0`; STATION_ID_NBR, AADT, AADT_YEAR (2025); 1,472 stations with AADT. Terms → V-38 |
| V-34 | Columbus open-data layers currency | 2026-09-26 | Meters item (2017) stale; curb inventory MapServer/38 current (edits to 2026-09-25) → S20 (ADR-0064); zoning S23/S23b current. Licence of layer 38 → V-37 |
| — | Downloader saved gzip-encoded responses still compressed (IPEDS zips failed with 'Bad magic number') | 2026-09-26 | Fixed: `decode_content = True`; cache scanned, no other file affected |
| V-13 | Overture release id and S3 path (S02 buildings) | 2026-09-25 | Release `2026-09-23.1` (S3 listing 2026-09-25); S02 buildings loaded live: 560,474 footprints. Places (S03a) still disabled — parking category/taxonomy part stays open as V-13b |
| V-14 | LODES8 latest Ohio year; WAC/xwalk columns | 2026-09-25 | LODES8 listing 2002–2023 (files dated 2025-12-03); `oh_wac_S000_JT00_2023.csv.gz` + `oh_xwalk.csv.gz` headers match the adapter; loaded 7,401 blocks |
| V-15 | ACS vintage and variable IDs; API key | 2026-09-25 | ACS 5-year 2024 (2025 → 404); all 11 variable IDs present in 2024 variables.json; key required (from env); loaded 1,033 block groups |
| V-16 | COTA GTFS URL | 2026-09-25 | `https://www.cota.com/data/cota.gtfs.zip` (Mobility Database mdb 404, official); feed 2026-09-07..2027-01-03; service_date 20261014; terms cota.com/data; loaded 2,975 stops |
| V-21 | FEMA NFHL layer 28 and floodway encoding | 2026-09-25 | Layer 28 = Flood Hazard Zones; ZONE_SUBTY = 'FLOODWAY', SFHA_TF = T/F. Full-detail geometry ~75 KB/polygon, so the query drops minimal-hazard X, pages 100 and generalizes ~1 m server-side (`maxAllowableOffset` 1e-5°); loaded 8,327 polygons |
| V-22 | EPA FRS/ACRES source and brownfield programs | 2026-09-25 | `geodata.epa.gov/.../OEI/FRS_INTERESTS/MapServer/0` (ACRES); fields REGISTRY_ID/PRIMARY_NAME/PGM_SYS_ACRNM; brownfield = ACRES; FIPS_CODE unreliable → spatial filter; loaded 40 sites |
| V-23 | 3DEP DEM access | 2026-09-25 | Replaced by one 3DEP ImageServer exportImage at 10 m (approved 2026-09-24; maxImage 8000²). First attempt 2026-09-25 returned **504 Gateway Time-out**; the identical request succeeded on one manual retry (16 s) — transient; slope built |
| — | S03b QA: 5 OSM POIs mapped as polygons at the study-area edge had their representative point outside StudyArea (7–211 ft) | 2026-09-25 | Fixed in code: points re-clipped after conversion; QA 57/57 pass |
| V-33 | TIGER/Line county URL pattern `TIGER{year}/COUNTY/tl_{year}_us_county.zip` (county only; the PLACE pattern is still unexercised) | 2026-09-24 | Live Franklin setup downloaded `tl_2025_us_county.zip` (83,989,800 bytes) and selected GEOID 39049 (543.609 sq mi); network smoke test `HEAD` returned 200 |
