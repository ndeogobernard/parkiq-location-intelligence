# Surface-Lot Parking Site Selection — Repeatable Location-Intelligence Workflow and Investment Package

**Project type:** Location-intelligence toolkit (market-agnostic site selection with financial underwriting)
**Business:** Development and operation of paid surface parking lots
**Client / users:** Partner group (investors and operators)
**Market:** Any U.S. city or submarket, defined per run by a market configuration file
**Document version:** 2.0 — 23 September 2026
**Document owner:** Bernard Issifu
**Executed by:** GIS Analyst / Developer (hereafter "the Analyst")
**Status:** Scoped — ready for build, then run per market

---

## 0. Read this first

This document is a complete handoff specification. It defines the business question, market definition and parameters, data sources, geodatabase design (a standalone reusable data model), the analytical methodology (demand, supply, gap, candidate screening, scoring, financial model, validation), automation (Python toolbox, ModelBuilder, CLI), visualization deliverables (static maps, map series, dashboard), communication deliverables (StoryMap and investment memo), the investment-package report structure, QA/QC plan, build timeline, per-market run procedure, deliverables checklist, acceptance criteria, and risks. The Analyst should be able to build the toolkit from this document and run it for any market without further scoping.

This is a **toolkit**, not a single study. It is built once, validated on a pilot market, and then run for every market the partners identify by adding one configuration file.

Where a value is marked **[VERIFY]**, confirm it against the live source before use. Where a value is marked **[PARAMETER]**, it lives in the market configuration and is reviewed for each market. Where a value is marked **[DECISION]**, the Analyst may choose, but must record the choice in the methods documentation.

Design principles:
1. **Market-agnostic inputs first.** Nationwide, standardized sources (Census, LODES, OpenStreetMap, Overture, Regrid, GTFS, FEMA, parking-app listings) so the workflow runs anywhere without re-engineering; city-specific open data (meters, citations, permits) as optional enrichment.
2. **Demand is modeled, not guessed.** Peak parking demand is estimated per location by daypart from land-use and activity data using published parking-generation rates, then compared to inventoried supply.
3. **Money is the ranking.** Sites are ranked primarily on projected return, not on a suitability score alone.
4. **Everything is reproducible.** One configuration file, one command, versioned outputs.

---

## 1. Background and business question

### 1.1 Business requirement

| Parameter | Requirement |
|---|---|
| Facility | Paid surface parking lot (no structure; no automated/mechanical systems) |
| Size | ~50–300 stalls per site [PARAMETER] |
| Customer | Any paying parker — commuters, visitors, event-goers, monthly permits; the objective is sustained occupancy across dayparts |
| Objective | Fill the lot reliably and generate a target return on total cost |
| Tenure | Purchase or ground lease (both modeled) |
| Markets | Multiple; identified by the partners over time |
| Deliverable | Full investment package per market: shortlist, site profiles, financial model, maps, dashboard, memo |

### 1.2 The analytical question

> **In a given market, which developable parcels can be operated as a paid surface lot that fills reliably across dayparts, and which of them offer the best risk-adjusted return given land cost, achievable rates, and unmet parking demand within a short walk?**

### 1.3 Objectives

1. Build a repeatable pipeline that ingests standardized data for any U.S. market and produces demand, supply, gap, candidate-site, scoring, and financial outputs.
2. Model parking demand by daypart (weekday day, weekday evening, weekend day, weekend evening, event) at walk-shed resolution.
3. Inventory existing off-street and on-street supply with capacity and rate estimates.
4. Screen and score candidate parcels for surface-lot suitability.
5. Underwrite each candidate with a per-site financial model (revenue, costs, NOI, valuation, payback, IRR, sensitivity).
6. Deliver a standard investment package per market.
7. Validate the demand model against observed rates and occupancy at existing lots in a pilot market and carry calibration forward.
8. Package the work as (a) the flagship toolkit and (b) a standalone reusable geodatabase/data-model project.

### 1.4 Non-goals

- Structured or automated parking (different cost, zoning, and engineering logic).
- Traffic engineering or curb-cut design (access is assessed qualitatively and flagged for due diligence).
- Legal entitlement determinations (zoning is screened from data; feasibility is confirmed in due diligence).

### 1.5 Success criteria (project level)

- A new market runs end to end with only a new configuration file.
- Every shortlisted site carries a complete financial profile with sensitivity.
- Pilot-market back-test reports modeled vs. observed performance and a documented calibration.

---

## 2. Market definition, study area, and coordinate systems

### 2.1 Market configuration (`markets/<slug>.yaml`)

Each market is defined by a configuration file. Required fields:

```yaml
market:
  name: "Example City, ST"
  slug: example_city
  boundary: {type: place|county|custom, value: "GEOID or path to polygon"}
  focus_submarkets: ["Downtown", "Medical District"]   # optional
  analysis_crs: EPSG:XXXX                                # local State Plane or UTM
  units: ft|m
site:
  min_parcel_sqft: 15000        # [PARAMETER] ~40–50 stalls minimum
  max_parcel_sqft: 200000
  target_stalls_range: [50, 300]
  stall_area_sqft_gross: 320    # [PARAMETER] gross area per stall incl. aisles (300–350 typical)
  layout_efficiency: 0.90
  setback_landscape_pct: 0.08
  max_slope_pct: 5
  min_frontage_ft: 60
  min_shape_index: 0.60
demand:
  walk_shed_minutes: [3, 5, 8]
  decay_weights: {3: 1.0, 5: 0.6, 8: 0.25}
  dayparts: [wd_day, wd_eve, we_day, we_eve, event]
  parking_generation_source: "ITE Parking Generation / ULI Shared Parking"  # [VERIFY license]
  transit_adjustment: {high_frequency_radius_m: 400, demand_factor: 0.85}
supply:
  private_effective_share: 0.50
  onstreet_stall_length_ft: 22
finance:
  land_cost_source: [regrid_assessed, listings]
  assessed_to_market_ratio: 1.20          # [PARAMETER] calibrated per market
  construction_cost_per_stall_usd: 6500   # [PARAMETER][VERIFY regional]
  soft_cost_pct: 0.15
  opex_per_stall_year_usd: 450            # [PARAMETER]
  property_tax_rate: 0.012
  new_entrant_rate_discount: 0.10
  occupancy_caps: {wd_day: 0.85, wd_eve: 0.60, we_day: 0.40, we_eve: 0.70, event: 0.90}
  target_cap_rate: 0.075
  hold_years: 10
  discount_rate: 0.12
ranking: {financial_weight: 0.70, suitability_weight: 0.30}
data_licenses:
  regrid: true
  foot_traffic: placer|advan|none
  parking_transactions: none
```

### 2.2 Study area

The market boundary plus a 1-mile buffer for network and anchor context. Analysis grid: H3 resolution 9 hexagons (~0.1 km²) [DECISION]. Focus submarkets, if given, are used for reporting and map insets, not as filters.

### 2.3 Coordinate reference systems

| Purpose | CRS |
|---|---|
| Storage and interchange | WGS 84 (EPSG:4326) |
| Analysis (area, distance, walk sheds) | Market `analysis_crs` (local State Plane or UTM) |
| Web delivery | WGS 84 Web Mercator (EPSG:3857) |

All source layers are reprojected on ingest; the source CRS and transformation are recorded in `DataSourceRegistry`.

---

## 3. Data sources

Core sources cover any U.S. market. Optional enrichment sources are added per market when available. Every source is registered per run with vintage, download date, license, and native CRS.

| ID | Category | Dataset | Coverage / access | Format | Use |
|---|---|---|---|---|---|
| **Core** | | | | | |
| S01 | Parcels | Regrid parcels (boundaries, owner, land use, assessed values, zoning add-on) | Nationwide / licensed (recommended); county open data fallback | GeoPackage/GeoJSON | Candidate universe, land cost |
| S02 | Buildings | Overture Buildings; Microsoft footprints | Nationwide / free | GeoParquet/GeoJSON | Improvement ratio, underutilization |
| S03 | Places | Overture Places; OpenStreetMap POIs | Nationwide / free | GeoParquet/PBF | Demand anchors |
| S04 | Jobs | Census LEHD LODES WAC (jobs by block, sector) | Nationwide / free | CSV | Employment demand |
| S05 | Population/vehicles | ACS 5-year block group: population, units in structure, vehicles available, tenure, commute mode | Nationwide / free | API/CSV | Residential and mode-share inputs |
| S06 | Existing parking | OSM `amenity=parking` (type, capacity, fee, levels); Overture parking places | Nationwide / free | PBF/GeoParquet | Supply inventory |
| S07 | Parking rates | SpotHero / ParkWhiz / ParkMobile facility listings (location, hourly/daily/monthly/event rates) | Most metros / public listings, API or scrape per terms [VERIFY] | JSON | Achievable rates, supply, price signal |
| S08 | Street network | OpenStreetMap via OSMnx; Esri StreetMap if licensed | Nationwide / free | Graph | Walk-time sheds, access |
| S09 | Transit | GTFS feeds (stops, frequencies) via Mobility Database | Most metros / free | GTFS | Transit adjustment, park-and-ride |
| S10 | Events | Venue capacity (OSM/Overture stadium, arena, theater, convention center); event calendars (Ticketmaster Discovery API, venue sites) | Nationwide / free or API | JSON | Event daypart demand |
| S11 | Hotels | Overture/OSM hotels (rooms where tagged); STR if licensed | Nationwide / free or licensed | GeoParquet | Overnight demand |
| S12 | Hospitals/universities | HIFLD hospitals (beds); IPEDS institutions (enrollment) | Nationwide / free | CSV/Shapefile | Visitor and staff demand |
| S13 | Traffic | State DOT AADT counts | Statewide / free | Shapefile | Visibility and access context |
| S14 | Flood | FEMA National Flood Hazard Layer | Nationwide / free | Shapefile/service | Constraint |
| S15 | Environmental | EPA FRS and ACRES brownfields | Nationwide / free | CSV/service | Constraint or opportunity flag |
| S16 | Land listings | CoStar / LoopNet / Crexi (asking price, size) | Metros / licensed or public | CSV | Land-cost calibration |
| S17 | Construction cost | RSMeans city cost index or regional contractor quotes | Nationwide / licensed or quotes | Table | Cost model |
| S18 | Elevation | USGS 3DEP 10 m DEM | Nationwide / free | GeoTIFF | Slope |
| **Optional enrichment** | | | | | |
| S19 | Foot traffic | Placer.ai or Advan patterns (visits by hour to POIs and lots) | Licensed | CSV/API | Demand calibration |
| S20 | Meter transactions | City parking meter/kiosk transactions | Many cities / open data | CSV | On-street occupancy and rates |
| S21 | Citations | Parking citations | Many cities / open data | CSV | Demand pressure, enforcement |
| S22 | Permits/planning | Building permits, planned garages | City / open data | CSV/GeoJSON | Pipeline competition |
| S23 | Zoning | Municipal zoning (if not in Regrid) | City / open data | Shapefile | By-right screen |
| S24 | Parking inventory | City off-street inventory studies | City | PDF/CSV | Supply calibration |

---

## 4. Geodatabase design and management (standalone portfolio project)

### 4.1 Deliverable

- `ParkIQ_<market>.gpkg` (GeoPackage, primary; produced per market run) and a file geodatabase export `ParkIQ_<market>.gdb` for ArcGIS Pro.
- `schema/schema.yaml` — machine-readable schema used by the `BuildSchema` tool; identical structure for every market.
- `docs/ERD.png` and `docs/ERD.drawio`; `docs/DataDictionary.md`; `docs/GDB_DesignRationale.md` (portfolio write-up).

### 4.2 Feature datasets and feature classes

Stored in the market `analysis_crs`. Naming: `PascalCase` feature classes, `snake_case` fields; every feature class carries `source_id`, `run_id`, and `load_ts`.

| Feature dataset | Feature class | Geometry | Key fields |
|---|---|---|---|
| `Reference` | `MarketBoundary` | Polygon | `name, geoid, area_sqmi` |
| `Reference` | `Submarkets` | Polygon | `name, type` |
| `Reference` | `HexGrid` | Polygon | `hex_id (H3 r9), submarket, area_km2` |
| `Reference` | `WalkNodes`, `WalkEdges` | Point/Polyline | OSMnx node/edge fields, `length_m, walk_minutes` |
| `Reference` | `Slope_pct` | Raster | Percent slope from DEM |
| `Cadastral` | `Parcels` | Polygon | `parcel_id, apn, address, owner, owner_type (domain), land_use_code, land_use_class (domain), zoning_code, zoning_screen (domain), lot_sqft, assessed_land_value, assessed_improvement_value, improvement_value_ratio, year_built, frontage_ft, shape_index, corner_flag, listing_price, listing_source` |
| `Cadastral` | `Buildings` | Polygon | `bldg_id, area_sqft, height_m, levels` |
| `Demand` | `DemandAnchors` | Point | `anchor_id, category (domain), name, size_metric (domain), size_value, drive_share, source_id` |
| `Demand` | `TransitStops` | Point | `stop_id, route_count, peak_headway_min, high_frequency_flag` |
| `Demand` | `Venues` | Point | `venue_id, name, seats, events_per_year, event_calendar_source` |
| `Supply` | `SupplyFacilities` | Point/Polygon | `facility_id, name, type (domain), capacity_stated, capacity_est, capacity_source, fee_flag, private_flag, rate_hour, rate_day, rate_month, rate_event, operator, source_id` |
| `Supply` | `OnStreetSegments` | Polyline | `segment_id, length_ft, stalls_est, metered_flag, permit_flag, rate_hour` |
| `Supply` | `RateSurface_<daypart>` | Raster | Interpolated achievable rate |
| `Analysis` | `Hex_Demand_Daypart` | Polygon/table | `hex_id, daypart, demand_stalls, components_json, method` |
| `Analysis` | `Hex_Supply_Daypart` | Polygon/table | `hex_id, daypart, supply_stalls, effective_supply_stalls` |
| `Analysis` | `Hex_Gap_Daypart` | Polygon/table | `hex_id, daypart, gap_stalls, gap_ratio, rate_index` |
| `Analysis` | `HotZones` | Polygon | `zone_id, dayparts_positive, total_gap_stalls, mean_rate_index` |
| `Analysis` | `CandidateParcels` | Polygon | `parcel_id, screen_status (domain), screen_reason, walk_min_to_hotzone, brownfield_flag, flood_flag, pipeline_flag, slope_pct` |
| `Analysis` | `WalkSheds` | Polygon | `parcel_id, minutes (3/5/8)` |
| `Results` | `SiteScores` | Polygon | `parcel_id, run_id, scenario (domain), c01_raw … c10_raw, c01_s … c10_s, composite, rank` |
| `Results` | `SiteFinancials` | Polygon | `parcel_id, run_id, stalls, land_cost, construction_cost, soft_cost, total_cost, occ_wd_day … occ_event, rate_wd_day … rate_event, annual_revenue, opex, noi, yield_on_cost, value_at_cap, payback_years, irr_10yr, npv, tenure (buy/lease), sensitivity_json` |
| `Results` | `Shortlist` | Polygon | `parcel_id, run_id, final_rank, recommended_flag, alternate_flag, profile_page_no, due_diligence_flags, notes` |

### 4.3 Standalone tables

| Table | Purpose | Key fields |
|---|---|---|
| `DataSourceRegistry` | Provenance | `source_id, provider, dataset, endpoint, vintage, download_date, license, native_crs, transformation, notes` |
| `ParkingRates` | Generation rates by category and daypart | `category, daypart, rate, unit, source_citation, calibration_factor` |
| `CriteriaDefinitions` | Scoring criteria | `criterion_id, name, description, unit, direction, normalization` |
| `WeightScenarios` | Weights | `scenario, criterion_id, weight` |
| `FinanceParams` | Resolved financial parameters per run | `run_id, param, value` |
| `ScoreRuns` | Run log | `run_id, market, scenario, timestamp, toolbox_version, git_commit, params_json, candidate_cnt` |
| `QAQC_Log` | QA results | `check_id, run_id, layer, check_name, result, count, threshold, passed, timestamp` |
| `Validation` | Back-test results | `run_id, facility_id, observed_metric, observed_value, modeled_value, error_pct` |

### 4.4 Domains

| Domain | Type | Values |
|---|---|---|
| `dm_LandUseClass` | coded | Vacant, SurfaceParking, Commercial, Industrial, Residential, MixedUse, Institutional, Other |
| `dm_OwnerType` | coded | Private, Corporate, Public, Institutional, Unknown |
| `dm_ZoningScreen` | coded | ByRight, Conditional, Prohibited, Unknown |
| `dm_AnchorCategory` | coded | Office, Medical, University, Hotel, RestaurantBar, Retail, Venue, Transit, ResidentialBlock, Government, Other |
| `dm_SizeMetric` | coded | Jobs, Beds, Enrollment, Rooms, Seats, Sqft, Units, Count |
| `dm_SupplyType` | coded | Surface, Garage, OnStreet, Mixed |
| `dm_Daypart` | coded | wd_day, wd_eve, we_day, we_eve, event |
| `dm_ScreenStatus` | coded | Pass, Fail, Review |
| `dm_Scenario` | coded | Balanced, DemandFirst, CostFirst |
| `dm_Direction` | coded | Benefit, Cost |
| `rg_Score` | range | 0–100 |
| `rg_Occupancy` | range | 0–1 |

### 4.5 Subtypes, relationships, topology, rules

- **Subtypes:** `Parcels` by `land_use_class`; `SupplyFacilities` by `type`.
- **Relationship classes:** `CandidateParcels` 1:M `SiteScores`; `CandidateParcels` 1:1 `SiteFinancials`; `CandidateParcels` 1:M `WalkSheds`; `ScoreRuns` 1:M `SiteScores`; `WeightScenarios` M:1 `CriteriaDefinitions`; `DataSourceRegistry` 1:M each source-derived class; `Venues` 1:M `DemandAnchors`.
- **Topology:** `Parcels` must not overlap (cluster tolerance 0.1 ft); `HexGrid` must not overlap or gap.
- **Attribute rules:** `lot_sqft = Shape_Area` (units per market); `improvement_value_ratio = assessed_improvement_value / NULLIF(assessed_land_value,0)`; constraint `composite BETWEEN 0 AND 100`; constraint occupancy fields in [0, 1].
- **Metadata:** ISO 19139 on every class; process steps appended from `ScoreRuns`.
- **Versioning:** immutable raw layers in `Raw` feature dataset; outputs keyed by `run_id`; `Shortlist` reflects the latest approved run; `parkiq compare` diffs runs.

### 4.6 Standalone write-up contents

Design goals; why one schema for all markets; ERD; domain and subtype rationale; walk-shed and hex design; relationship classes in action; run versioning; QA log summary; 60-second screen capture.

---

## 5. Analytical methodology

### 5.1 Phase A — Market setup

Resolve the boundary; pull all core sources for the boundary plus buffer; build the pedestrian network (OSMnx `walk` network with walking speed 1.3 m/s [PARAMETER]); generate the H3 grid; compute slope; register sources; run ingest QA.

### 5.2 Phase B — Demand model (hex × daypart)

1. **Anchor extraction:** classify POIs and blocks into demand categories with a size metric: office/industrial jobs (LODES), hospital beds (HIFLD), university enrollment (IPEDS), hotel rooms, venue seats and events per year, restaurant/bar and retail counts or floor area (Overture/OSM; building area as proxy), residential units in multi-unit structures with low vehicle availability (ACS).
2. **Parking generation:** apply rates per category and daypart from `ParkingRates` (e.g., office weekday day ≈ 0.8 stalls per employee; hotel evening ≈ 0.9–1.2 per room; restaurant/bar evening peaks; venue = seats × drive share ÷ persons per car on event days) [VERIFY rates against ITE/ULI; cite]. Apply **driver mode share** from ACS commute mode and the transit adjustment near high-frequency stops [PARAMETER].
3. **Spatial allocation:** distribute each anchor's demand across hexes within its walk-shed using the decay weights (1.0 at ≤ 3 min, 0.6 at 5 min, 0.25 at 8 min) [PARAMETER]; sum to `Hex_Demand_Daypart`, retaining components for auditability.
4. **Calibration:** in the pilot market (and any market with S19/S20), scale category rates so modeled demand matches observed occupancy/visits; store factors in `ParkingRates.calibration_factor`.

### 5.3 Phase C — Supply inventory

1. Merge OSM/Overture parking, app listings, and city inventories; deduplicate by location (40 m) and name.
2. **Capacity:** stated where present; else surface = area ÷ gross stall area × efficiency; garage = footprint × levels ÷ gross stall area; on-street = curb length ÷ stall length with meter/permit flags.
3. **Rates:** attach listed rates; build an inverse-distance-weighted **rate surface** per daypart; cross-validate.
4. Allocate supply to hexes with the same decay; count private/reserved supply at the effective share [PARAMETER]; write `Hex_Supply_Daypart`.

### 5.4 Phase D — Gap analysis

`gap_stalls = demand − effective_supply` and `gap_ratio = demand / supply` per hex and daypart; `rate_index` = rate surface normalized. **Hot zones** = contiguous hexes with weekday-day gap > 0 and evening or event gap > 0 (multi-daypart demand is what keeps a surface lot full). Write `Hex_Gap_Daypart`, `HotZones`.

### 5.5 Phase E — Candidate parcel screen (hard filters) [PARAMETER]

- `lot_sqft` within min/max; `shape_index ≥ 0.60`; `frontage_ft ≥ 60` on a public street.
- Land use in (Vacant, SurfaceParking, low-value improvement with `improvement_value_ratio < 0.25`, auto-oriented commercial); exclude residential-zoned unless `zoning_screen` allows commercial parking.
- `zoning_screen` in (ByRight, Conditional, Unknown) — Unknown flagged, not excluded.
- Not in floodway; `slope_pct < max`; not park/cemetery/right-of-way; no active development permit (S22).
- Within an 8-minute walk of a hot zone.
Write `CandidateParcels` with `screen_reason` for every evaluated parcel. Expect 40–200 Pass candidates; adjust size or walk thresholds per the recorded rule if outside that range.

### 5.6 Phase F — Network analysis

Walk-sheds (3/5/8 min) from each candidate; walk time to the top-3 anchors by demand; count of competing facilities within 3 min; population and jobs within 5 min. Write `WalkSheds`.

### 5.7 Phase G — Criteria and scoring

| ID | Criterion | Measure | Direction |
|---|---|---|---|
| C01 | Unmet demand, weekday day | Gap stalls in 5-min shed | Benefit |
| C02 | Unmet demand, evening/weekend | Gap stalls (wd_eve + we_day + we_eve) in 5-min shed | Benefit |
| C03 | Event demand | Event gap stalls in 8-min shed × events per year | Benefit |
| C04 | Achievable rate | Rate index at parcel (weighted dayparts) | Benefit |
| C05 | Competing supply | Effective supply stalls within 3 min | Cost |
| C06 | Anchor proximity | Mean walk minutes to top-3 anchors | Cost |
| C07 | Land cost | Land cost per buildable stall | Cost |
| C08 | Access quality | Corner flag, arterial frontage, AADT visibility, curb-cut feasibility score | Benefit |
| C09 | Zoning certainty | ByRight = 100, Conditional = 60, Unknown = 40 | Benefit |
| C10 | Pipeline risk | Planned garages/developments within 5 min | Cost |

Normalization: winsorize 5th/95th, min–max to 0–100, invert costs. Scenarios `Balanced`, `DemandFirst`, `CostFirst` (Appendix B). Sensitivity: OAT ± 25% and 1,000 Dirichlet draws; report rank stability.

### 5.8 Phase H — Financial model (per candidate)

- **Stalls** = `lot_sqft × (1 − setback_landscape_pct) × layout_efficiency ÷ stall_area_sqft_gross`.
- **Occupancy by daypart** = f(gap_ratio in 5-min shed), capped per config; **rates** from the rate surface less the new-entrant discount; monthly-permit share in office-heavy zones [PARAMETER].
- **Revenue** = Σ dayparts (stalls × occupancy × rate × billable hours or turns × days per year) + events (events per year × stalls × event occupancy × event rate).
- **Costs:** land (assessed × market ratio, listing, or ground-lease rent), construction per stall + soft costs; opex (maintenance, insurance, payment/LPR tech fees, enforcement, property tax, management).
- **Returns:** NOI, yield-on-cost, value at target cap rate, payback, 10-year IRR and NPV under buy and ground-lease; **sensitivity** on occupancy ± 15 pts, rate ± 20%, land ± 20%, construction ± 15%; tornado chart per site.
- **Final ranking** = financial return (70%) + suitability composite (30%) [PARAMETER]; top 5–10 shortlisted; one recommended site and one alternate.

### 5.9 Phase I — Validation and back-test (pilot market)

Select 10–20 existing paid surface lots; compare modeled occupancy and rates to observed (foot-traffic data, app availability snapshots at peak hours, meter data, site visits); write `Validation`; report error and recalibrate `ParkingRates`.

### 5.10 Phase J — Due-diligence flags

Per shortlisted site: title/ownership, environmental (brownfield), stormwater, curb-cut approval, zoning confirmation, adjacent development plans, ground-lease vs. purchase, operator/tech setup. Listed, not resolved.

---

## 6. Automation, Python toolbox, ModelBuilder, and CLI

### 6.1 Environment

Python 3.11: `geopandas`, `shapely`, `osmnx`, `pandana`, `h3`, `pyarrow`, `duckdb`, `requests`, `pyproj`, `rasterio`, `numpy`, `pandas`, `openpyxl`/`xlsxwriter`, `matplotlib`/`plotly`, `typer`, `pydantic`, `pytest`. ArcGIS Pro 3.x with ArcPy for the toolbox wrapper, Network Analyst (optional alternative to OSMnx) [DECISION], and cartography.

### 6.2 Repository layout

```
parkiq/
├── README.md                      # onboarding a new market in one day
├── configs/parking_rates.yaml · weights.yaml · finance_defaults.yaml · criteria.yaml
├── markets/<slug>.yaml            # one per market
├── schema/schema.yaml
├── toolbox/ParkIQ.pyt · ParkIQ.pyt.xml · models/ParkIQ_Models.tbx · diagrams/
├── parkiq/
│   ├── setup.py · ingest/ (regrid, overture, osm, lodes, acs, gtfs, listings, events, fema, epa, dem, city_open_data)
│   ├── demand.py · supply.py · gap.py · screen.py · network.py · score.py · finance.py · validate.py
│   ├── report.py (memo, site profiles) · maps.py · dashboard.py · compare.py · cli.py
├── arcgis/ParkIQ_Template.aprx · layouts/ · export_map_series.py
├── templates/memo.docx · site_profile.html · financial_model.xlsx · storymap_outline.md
├── tests/ (unit tests: allocation, capacity, finance; fixture market)
└── outputs/<market>/<run_id>/ (gpkg, gdb, maps/, map_series/, model.xlsx, memo.docx, dashboard/, data_sources.csv, params.yaml, run_log.json)
```

### 6.3 Python toolbox `ParkIQ.pyt` — tool specifications

Each tool validates parameters, logs to `outputs/.../logs/<run_id>.log`, writes `ScoreRuns`, and is idempotent per `run_id`.

| # | Tool | Parameters | Reads | Writes |
|---|---|---|---|---|
| 1 | `BuildSchema` | `schema_yaml, out_gpkg/gdb, crs` | config | all layers, domains, relationships, topology |
| 2 | `SetupMarket` | `market_yaml` | boundary | `MarketBoundary, Submarkets, HexGrid, WalkNodes/Edges, Slope_pct` |
| 3 | `IngestSources` | `market_yaml, source_ids` | S01–S24 | `Parcels, Buildings, DemandAnchors, TransitStops, Venues, SupplyFacilities, OnStreetSegments`, `DataSourceRegistry` |
| 4 | `RunQAQC` | `gpkg, layers, run_id` | layers | `QAQC_Log` |
| 5 | `BuildDemand` | `gpkg, run_id, rates_yaml` | anchors, network, grid | `Hex_Demand_Daypart` |
| 6 | `BuildSupply` | `gpkg, run_id` | facilities, listings | `Hex_Supply_Daypart`, `RateSurface_*` |
| 7 | `ComputeGap` | `gpkg, run_id` | demand, supply | `Hex_Gap_Daypart`, `HotZones` |
| 8 | `ScreenCandidates` | `gpkg, run_id, market_yaml` | parcels, constraints, hot zones | `CandidateParcels` |
| 9 | `BuildWalkSheds` | `gpkg, run_id, minutes` | candidates, network | `WalkSheds` |
| 10 | `ComputeCriteriaScores` | `gpkg, run_id, criteria_yaml` | all | `SiteScores` (raw, normalized) |
| 11 | `WeightedSuitability` | `gpkg, run_id, weights_yaml, scenario` | `SiteScores` | composite, rank |
| 12 | `SensitivityRunner` | `gpkg, run_id, scenario, oat_pct, draws, seed` | `SiteScores` | rank-stability table |
| 13 | `FinancialModel` | `gpkg, run_id, market_yaml` | candidates, gap, rates | `SiteFinancials`, `model.xlsx` |
| 14 | `BuildShortlist` | `gpkg, run_id, top_n` | scores, financials | `Shortlist`, site-profile index |
| 15 | `Validate` | `gpkg, run_id, observed_csv` | supply, demand | `Validation`, calibration factors |
| 16 | `ExportPackage` | `gpkg, run_id, aprx` | all | maps, map series, dashboard data, memo |
| 17 | `CompareRuns` | `run_a, run_b` | two runs | diff report |

CLI equivalents: `parkiq run --market markets/<slug>.yaml --steps all`, `parkiq validate`, `parkiq package`, `parkiq compare`.

### 6.4 ModelBuilder deliverable

`ParkIQ_Models.tbx` with `M1_DemandSupplyGap` (Anchors → Walk-shed allocation → Demand; Facilities → Capacity → Supply; Gap) and `M2_ScreenScoreRank` (Parcels → Screen → Walk sheds → Criteria → Weighted sum → Rank). Export diagrams to `toolbox/diagrams/`.

### 6.5 Engineering standards

Config-driven (no hard-coded thresholds); `run_id` = `YYYYMMDD_HHMM_<market>_<scenario>` with git commit in `ScoreRuns`; unit tests for allocation, capacity, normalization, weighting, and every finance formula (Python and Excel results must match); logging; resume from any step; versioned outputs; `README` onboarding checklist for a new market.

---

## 7. Visualization deliverables

### 7.1 Cartographic standards

Layout template (`ParkIQ_Template.pagx`): market name, run date and version, legend, scale bar, north arrow, sources and vintages, parameter version, disclaimer (returns are modeled estimates pending due diligence). Basemap: Esri Light Gray Canvas for analytical maps; imagery for site profiles. Sequential palette for demand/gap; categorical for zoning screen; diverging for scenario deltas. Identical templates across markets so partners can compare.

### 7.2 Static maps (PDF + PNG, `outputs/.../maps/`)

| # | Map | Content |
|---|---|---|
| M01 | Market context | Boundary, submarkets, major roads, transit, venues, hospitals, universities |
| M02 | Demand anchors | Anchors sized by demand contribution, by category |
| M03 | Demand — weekday day | Hex demand stalls |
| M04 | Demand — evening/weekend | Hex demand stalls |
| M05 | Demand — event | Hex demand stalls with venues |
| M06 | Existing supply and rates | Facilities by type/capacity; rate surface |
| M07 | Gap — weekday day | Hex gap and hot zones |
| M08 | Gap — evening/weekend | Hex gap |
| M09 | Candidate screening | Evaluated parcels by `screen_status`; fail-reason inset |
| M10 | Suitability — Balanced | Candidates by composite class; top 10 labeled |
| M11 | Suitability — DemandFirst / CostFirst | Small multiples |
| M12 | Rank stability | Candidates by top-10 frequency |
| M13 | Financial ranking | Candidates by yield-on-cost; shortlist highlighted |
| M14 | Shortlist overview | Top sites with 5-min walk sheds and anchors |
| M15 | Recommended site | Site at 1:2,400 with walk sheds, competitors and rates, access notes |

### 7.3 Map series (multipage PDFs)

- **Site Profile Map Series** (`MS01_SiteProfiles.pdf`): one page per shortlisted site, index layer `Shortlist`: aerial with parcel outline and conceptual stall layout, 3/5/8-min walk sheds, anchors, competitors with rates, dynamic text (stalls, land cost, total cost, occupancy by daypart, revenue, NOI, yield-on-cost, IRR, payback, zoning screen, due-diligence flags), sensitivity tornado image.
- **Daypart Map Series** (`MS02_Dayparts.pdf`): one page per daypart showing demand, supply, and gap side by side.
- **Submarket Series** (`MS03_Submarkets.pdf`, optional): one page per focus submarket.

### 7.4 Dashboard

ArcGIS Online Dashboard (hosted layers) or a Plotly/Kepler.gl HTML [DECISION]: scenario and daypart selectors; map of candidates by score/return; list ranked by final rank; indicators (stalls, NOI, yield, IRR) for the selected site; charts (top-10 by return; criterion contributions; occupancy by daypart); details panel with due-diligence flags. Mobile layout.

---

## 8. Communication — ArcGIS StoryMap (investment briefing)

Title: *"Where a Surface Lot Pays: <Market> Parking Site Selection"*. Audience: the partners and their lenders.

| # | Section | Content |
|---|---|---|
| 1 | Cover | Market map with recommended site; one-line thesis |
| 2 | The opportunity | Business requirement and what the study answers |
| 3 | Where demand comes from | Anchors and daypart demand (M02–M05) |
| 4 | Who we compete with | Supply and rates (M06) |
| 5 | Where the gap is | Hot zones (M07–M08) |
| 6 | Finding the land | Screening rules and candidate pool (M09) |
| 7 | Scoring and money | Suitability and financial ranking (M10–M13); embedded dashboard |
| 8 | How stable is the answer | Sensitivity and scenario comparison (M12) |
| 9 | The shortlist | Site-profile cards |
| 10 | The recommendation | Recommended and alternate sites; returns; risks; due-diligence checklist |
| 11 | Method and data | Links to memo, model, data appendix, repo |

---

## 9. Investment package report (per market)

`outputs/<market>/<run_id>/Investment_Memo.docx/pdf` (10–15 pages plus appendices): executive summary (recommendation and headline returns) → business requirement → market overview → demand analysis → supply and rates → gap and hot zones → candidate screening → suitability scoring and sensitivity → financial model and ranking → shortlist and site profiles → recommendation, risks, and due-diligence plan → assumptions and limitations → reproducibility (run ID, parameters). Appendices: A data sources and vintages; B parking-rate table and calibration; C parameters; D QA/QC summary; E map gallery; F full financial model (Excel attached).

---

## 10. QA/QC plan

| Stage | Check | Threshold / expectation |
|---|---|---|
| Ingest | CRS = `analysis_crs`; extents within buffer | 100% |
| Ingest | Invalid/null geometry; duplicate `parcel_id`, `facility_id` | 0 after repair |
| Anchors | Category coverage report; manual review of top-50 anchors by demand | Reviewed |
| Demand | Downtown weekday demand within ±25% of published study or supply × observed occupancy where available | Reported |
| Supply | Stated vs. estimated capacity error on facilities with stated capacity | ≤ 20% |
| Rates | Cross-validated rate-surface error on held-out listings | ≤ 20% |
| Screen | Every evaluated parcel has a `screen_reason` | 100% |
| Scoring | Weights sum to 1.00; composite in [0,100]; unique ranks | exact |
| Finance | Python vs. Excel results | Match to the dollar |
| Sensitivity | Seed recorded; reproducible | Re-run matches |
| Maps | Title, legend, scale, sources, run version on every map | Checklist |
| Package | Every memo number traces to `SiteFinancials` or `SiteScores` | Traced |

Peer review: one independent reviewer reproduces the pilot run from the README before the toolkit is marked complete.

---

## 11. Timeline — build (8 weeks, part-time) and per-market run

| Week | Milestone | Exit criteria |
|---|---|---|
| 1 | Config schema; `SetupMarket`; core ingest (free sources); H3 grid; walk network | Pilot market boundary and network built |
| 2 | Regrid/listings ingest; `BuildSchema`; ERD; data dictionary v1 | Schema builds clean; parcels loaded |
| 3 | Supply inventory, capacity estimation, rate surface | Supply QA passes |
| 4 | Demand model with rates table; allocation; gap and hot zones | `Hex_Gap_Daypart`, `HotZones` complete |
| 5 | Candidate screen; walk sheds; scoring; scenarios; sensitivity | Candidate pool 40–200; rank-stability table |
| 6 | Financial model (Python + Excel template); shortlist | `SiteFinancials` and `model.xlsx` match |
| 7 | Maps, site-profile map series, dashboard, memo generator, StoryMap | Package exports end to end |
| 8 | Pilot validation and calibration; tests; README onboarding; peer reproduction | Acceptance criteria met |

**Per market after build:** Day 1 config and data pulls; Day 2 run and QA review; Days 3–4 calibration (if data) and package polish; Day 5 partner briefing. Faster as markets accumulate.

---

## 12. Deliverables checklist

**A. Flagship toolkit**
- [ ] Repository per Section 6.2 with README and new-market onboarding checklist
- [ ] `ParkIQ.pyt` (17 tools) and CLI; ModelBuilder models with diagrams; tests
- [ ] Configs: `parking_rates.yaml` (cited), `weights.yaml`, `finance_defaults.yaml`, `criteria.yaml`
- [ ] ArcGIS Pro template (`.aprx`, layouts, map series)
- [ ] Excel financial model template with live formulas
- [ ] Memo and site-profile templates; StoryMap outline
- [ ] Dashboard template
- [ ] Pilot-market run: full investment package, validation report, calibration factors
- [ ] Documentation: methods, parameters, limitations, tool reference
- [ ] Portfolio page (toolkit overview, pilot findings, sample package)

**B. Standalone geodatabase / data-model project**
- [ ] `docs/GDB_DesignRationale.md`, ERD, data dictionary
- [ ] `schema.yaml` and `BuildSchema` tool
- [ ] Run-versioning and `CompareRuns` demonstration
- [ ] 60-second screen capture (domains, relationships, topology validation, run diff)
- [ ] Portfolio page

**Per-market package (produced by each run)**
- [ ] `ParkIQ_<market>.gpkg` and `.gdb`
- [ ] Static maps M01–M15; map series MS01–MS02 (MS03 optional)
- [ ] Dashboard; StoryMap
- [ ] Investment memo with appendices; Excel model
- [ ] Data-source register, parameters, run log

---

## 13. Acceptance criteria

1. `parkiq run --market <new market>` completes end to end on a market not previously seen, with only a new configuration file, and produces the full package.
2. `BuildSchema` recreates the data model on a clean machine; a schema-diff script confirms outputs match the documented design.
3. Pilot-market back-test reports modeled vs. observed occupancy/rates for ≥ 10 existing lots with documented calibration factors.
4. Every shortlisted site has stalls, occupancy and rate by daypart, revenue, costs, NOI, yield-on-cost, IRR, payback, tenure comparison, and a sensitivity chart; the Excel model reproduces the Python figures.
5. Every evaluated parcel carries a `screen_reason`; every map carries sources and run version; every memo number traces to a table.
6. Scenario rank stability is reported; the recommended site is top-3 under all three scenarios or the deviation is explained.
7. Runs are versioned and `CompareRuns` produces a shortlist diff.
8. One independent reviewer reproduces the pilot run from the README.

---

## 14. Assumptions, risks, and mitigations

| Item | Risk | Mitigation |
|---|---|---|
| Parking-generation rates | ITE/ULI manuals licensed; rates context-dependent | License or use published summaries; calibrate per market; single cited config |
| Zoning data gaps | Commercial-parking permissibility unclear | Screen as Unknown, not excluded; confirm in due diligence; add city zoning when available |
| Rates and occupancy | Listings show asking, not realized, rates | New-entrant discount; app availability snapshots; foot-traffic data where budgeted |
| Land price | Assessed values lag market | Listing calibration ratio per market; ground-lease scenario |
| Pipeline competition | New garages not in data | Permit/planning feeds; manual check of top-10 sites |
| Over-fitting to pilot | Calibration not transferable | Per-market calibration factors; report uncalibrated results alongside |
| Events | Lumpy revenue | Calendar-based event counts; sensitivity on event count |
| Data licenses | Regrid or foot-traffic budget not approved | County parcel fallback adapter; uncalibrated demand with wider sensitivity bands |
| Access/engineering | Curb cuts or stormwater may block a site | Due-diligence flags; access score is qualitative |

---

## Appendix A — Mapping to the business requirement

| Requirement | Where addressed |
|---|---|
| Repeatable for any market | Sections 0, 2.1, 6 (config-driven CLI, one schema, onboarding checklist) |
| Surface lot only | Section 1.1, 5.5 screen, 5.8 cost model |
| Fill the lot and profit | Sections 5.2–5.4 (multi-daypart demand and gap), 5.8 (financial ranking) |
| Full investment package | Sections 7–9, 12 (per-market package) |
| All kinds of data | Section 3 (core free + licensed enrichment) |
| Partners can test assumptions | Excel model with live inputs; dashboard scenario/daypart selectors |
| Defensible and auditable | `screen_reason`, `components_json`, `ScoreRuns`, `QAQC_Log`, `Validation` |

## Appendix B — Scoring weights (`configs/weights.yaml`)

```yaml
Balanced:    {C01: 0.18, C02: 0.14, C03: 0.08, C04: 0.12, C05: 0.10, C06: 0.08, C07: 0.12, C08: 0.08, C09: 0.05, C10: 0.05}
DemandFirst: {C01: 0.25, C02: 0.18, C03: 0.10, C04: 0.12, C05: 0.08, C06: 0.07, C07: 0.06, C08: 0.06, C09: 0.04, C10: 0.04}
CostFirst:   {C01: 0.12, C02: 0.10, C03: 0.05, C04: 0.12, C05: 0.10, C06: 0.06, C07: 0.25, C08: 0.08, C09: 0.06, C10: 0.06}
ranking: {financial_weight: 0.70, suitability_weight: 0.30}
```

## Appendix C — Parking-rate table structure (`configs/parking_rates.yaml`)

```yaml
office:        {unit: employee, wd_day: 0.80, wd_eve: 0.05, we_day: 0.05, we_eve: 0.02, event: 0.00, source: "ITE PG 6th ed. LU 701 [VERIFY]"}
medical:       {unit: bed,      wd_day: 2.50, wd_eve: 0.80, we_day: 0.90, we_eve: 0.50, event: 0.00, source: "[VERIFY]"}
university:    {unit: student,  wd_day: 0.25, wd_eve: 0.10, we_day: 0.05, we_eve: 0.05, event: 0.00, source: "[VERIFY]"}
hotel:         {unit: room,     wd_day: 0.40, wd_eve: 1.00, we_day: 0.50, we_eve: 1.10, event: 0.00, source: "[VERIFY]"}
restaurant_bar:{unit: sqft_k,   wd_day: 6.0,  wd_eve: 14.0, we_day: 8.0,  we_eve: 16.0, event: 0.00, source: "[VERIFY]"}
retail:        {unit: sqft_k,   wd_day: 2.5,  wd_eve: 2.0,  we_day: 3.5,  we_eve: 2.5,  event: 0.00, source: "[VERIFY]"}
venue:         {unit: seat,     wd_day: 0.00, wd_eve: 0.00, we_day: 0.00, we_eve: 0.00, event: 0.33, source: "seats × drive share 0.85 ÷ 2.6 persons/car [VERIFY]"}
residential:   {unit: unit_no_offstreet, wd_day: 0.30, wd_eve: 0.90, we_day: 0.80, we_eve: 0.95, event: 0.00, source: "[VERIFY]"}
calibration_factors: {}   # filled per market by Validate
```

## Appendix D — Signature queries (to be benchmarked and documented)

```sql
-- Hot zones: hexes with unmet demand in weekday day AND (evening OR event)
SELECT d.hex_id
FROM Hex_Gap_Daypart d
JOIN Hex_Gap_Daypart e ON e.hex_id = d.hex_id AND e.daypart IN ('wd_eve','we_eve','event') AND e.gap_stalls > 0
WHERE d.daypart = 'wd_day' AND d.gap_stalls > 0
GROUP BY d.hex_id;

-- Shortlist with returns under all scenarios
SELECT f.parcel_id, f.stalls, f.noi, f.yield_on_cost, f.irr_10yr,
       MAX(CASE WHEN s.scenario='Balanced'    THEN s.rank END) AS rank_balanced,
       MAX(CASE WHEN s.scenario='DemandFirst' THEN s.rank END) AS rank_demand,
       MAX(CASE WHEN s.scenario='CostFirst'   THEN s.rank END) AS rank_cost
FROM SiteFinancials f JOIN SiteScores s USING (parcel_id, run_id)
WHERE f.run_id = :run_id
GROUP BY f.parcel_id, f.stalls, f.noi, f.yield_on_cost, f.irr_10yr
ORDER BY f.irr_10yr DESC LIMIT 10;
```

*End of document.*
