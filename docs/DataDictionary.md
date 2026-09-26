# ParkIQ data dictionary

Generated from `schema/schema.yaml` (version 1.0.0) by `parkiq schema-docs`. Do not edit by hand.

Every feature class also carries the lineage fields `source_id` (TEXT, Source ID from configs/sources.yaml (S00–S24) or DERIVED), `run_id` (TEXT, Run that wrote the row (ScoreRuns.run_id)), `load_ts` (DATETIME, UTC time the row was written). Feature classes are stored in the market's analysis CRS; `Raw_*` snapshots in EPSG:4326. BOOLEAN is stored as 0/1, JSON as text.

## Domains

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
| `dm_Tenure` | coded | Buy, Lease |
| `dm_ParkingZone` | coded | A, B |
| `rg_Score` | range | 0 – 100 |
| `rg_Occupancy` | range | 0 – 1 |

## Feature dataset `Reference`

### `MarketBoundary`

Market boundary (county/city) from TIGER/Line.

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `name` | TEXT | yes |  |  | Boundary name |
| `geoid` | TEXT | yes |  |  | Census GEOID |
| `area_sqmi` | REAL | yes |  |  | Area, square miles |

### `StudyArea`

Boundary plus buffer; the clip extent for every source (addition, ADR-0005).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `buffer_miles` | REAL | yes |  |  | Buffer distance, miles |
| `area_sqmi` | REAL | yes |  |  | Area, square miles |

### `Submarkets`

Analyst-defined submarkets (downtown, university, ...).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `name` | TEXT | yes |  |  | Submarket name |
| `type` | TEXT | yes |  |  | Submarket type |

### `HexGrid`

H3 resolution-9 grid clipped to the study area (ADR-0009).

Geometry: Polygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `hex_id` | TEXT | no | yes |  | H3 cell index |
| `submarket` | TEXT | yes |  |  | Submarket containing the cell centroid |
| `area_km2` | REAL | yes |  |  | Cell area, km² |

### `WalkNodes`

Pedestrian network nodes (OSMnx walk network).

Geometry: Point · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `node_id` | TEXT | no | yes |  | OSM node id |
| `street_count` | INTEGER | yes |  |  | Streets meeting at the node |

### `WalkEdges`

Pedestrian network edges with walk time at the configured speed.

Geometry: LineString · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `u` | TEXT | no |  |  | From node id |
| `v` | TEXT | no |  |  | To node id |
| `key` | INTEGER | yes |  |  | Parallel-edge key |
| `osmid` | TEXT | yes |  |  | OSM way id(s) |
| `highway` | TEXT | yes |  |  | OSM highway tag |
| `name` | TEXT | yes |  |  | Street name |
| `length_m` | REAL | no |  |  | Length, metres |
| `walk_minutes` | REAL | no |  |  | length_m / walk speed / 60 |

### `TrafficCounts`

State DOT traffic count stations/segments (AADT).

Geometry: Geometry · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `count_id` | TEXT | no |  |  | Station/segment id |
| `aadt` | REAL | yes |  |  | Annual average daily traffic |
| `year` | INTEGER | yes |  |  | Count year |
| `road` | TEXT | yes |  |  | Road name/route |

### `FloodHazard`

FEMA NFHL flood hazard zones.

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `fld_zone` | TEXT | yes |  |  | FEMA flood zone (A, AE, X, ...) |
| `zone_subty` | TEXT | yes |  |  | Zone subtype (e.g. FLOODWAY) |
| `sfha_flag` | BOOLEAN | yes |  |  | Special Flood Hazard Area |
| `floodway_flag` | BOOLEAN | yes |  |  | Regulatory floodway |

### `EnvSites`

EPA FRS/ACRES environmental interest sites.

Geometry: Point · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `site_id` | TEXT | no |  |  | EPA registry id |
| `name` | TEXT | yes |  |  | Site name |
| `program` | TEXT | yes |  |  | EPA program acronym(s) |
| `brownfield_flag` | BOOLEAN | yes |  |  | Brownfield program interest |

### `ZoningDistricts`

Municipal base zoning districts (addition, ADR-0060).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `zoning_code` | TEXT | no |  |  | District code as published (e.g. C4, LC4, UCR-R) |
| `jurisdiction` | TEXT | no |  |  | Zoning authority (e.g. Columbus) |
| `general_category` | TEXT | yes |  |  | Publisher's general category |
| `zoning_status` | TEXT | yes |  |  | Publisher's status |
| `ord_no` | TEXT | yes |  |  | Rezoning ordinance number |
| `case_number` | TEXT | yes |  |  | Zoning case number |

### `ZoningOverlays`

Zoning/planning overlays, coded to zoning-table overlay rows (addition, ADR-0060).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `overlay_code` | TEXT | no |  |  | Zoning-table key, e.g. overlay:UCO, overlay:University/NC |
| `overlay_name` | TEXT | yes |  |  | Published overlay name |
| `overlay_type` | TEXT | yes |  |  | Published overlay type |
| `jurisdiction` | TEXT | no |  |  | Zoning authority |
| `ord_no` | TEXT | yes |  |  | Ordinance number |

### `ParkingZones`

Downtown parking zones A/B; Franklin: derived from City Code Map 2 (S23c, [VERIFY]) (addition, ADR-0061).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `zone` | TEXT | no |  | `dm_ParkingZone` | Parking zone |
| `jurisdiction` | TEXT | no |  |  | Zoning authority |
| `method` | TEXT | yes |  |  | How the polygon was produced |
| `derived_date` | TEXT | yes |  |  | Date derived (ISO) |

## Feature dataset `Cadastral`

### `Parcels`

Tax parcels with land use, owner type, values and zoning.

Geometry: MultiPolygon · CRS: analysis CRS
 · Subtypes by `land_use_class`

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `parcel_id` | TEXT | no | yes |  | County parcel id |
| `apn` | TEXT | yes |  |  | Assessor parcel number (if different) |
| `address` | TEXT | yes |  |  | Site address |
| `owner` | TEXT | yes |  |  | Owner name as recorded |
| `owner_type` | TEXT | yes |  | `dm_OwnerType` | Owner class from ordered regex rules + overrides (due-diligence flag only) |
| `land_use_code` | TEXT | yes |  |  | County land-use code |
| `land_use_class` | TEXT | yes |  | `dm_LandUseClass` | Land-use class via the market crosswalk (subtype) |
| `auto_oriented_flag` | BOOLEAN | yes |  |  | Crosswalk: auto-oriented commercial use (addition, ADR-0060) |
| `excluded_use_flag` | BOOLEAN | yes |  |  | Crosswalk: park/cemetery/ROW/utility etc. (addition, ADR-0060) |
| `jurisdiction` | TEXT | yes |  |  | Municipality or township governing zoning (addition, ADR-0060) |
| `zoning_code` | TEXT | yes |  |  | Base zoning code (largest overlap) |
| `zoning_overlays` | TEXT | yes |  |  | Overlay codes, ';'-joined (addition, ADR-0060) |
| `parking_zone` | TEXT | yes |  | `dm_ParkingZone` | Downtown parking zone (addition, ADR-0061) |
| `parking_zone_near_boundary` | BOOLEAN | yes |  |  | Within the review distance of the A/B line (addition, ADR-0061) |
| `zoning_screen` | TEXT | yes |  | `dm_ZoningScreen` | Commercial-parking use class from the zoning table |
| `zoning_status` | TEXT | yes |  | `dm_ScreenStatus` | Zoning route: Pass/Review/Fail (addition, ADR-0059) |
| `zoning_reason` | TEXT | yes |  |  | Zoning result with confidence and citation (addition, ADR-0059) |
| `lot_sqft` | REAL | yes |  |  | Parcel area in square feet (= Shape_Area) |
| `assessed_land_value` | REAL | yes |  |  | Auditor land value (Franklin: 100% appraised) |
| `assessed_improvement_value` | REAL | yes |  |  | Auditor improvement value |
| `improvement_value_ratio` | REAL | yes |  |  | improvement / NULLIF(land, 0) |
| `year_built` | INTEGER | yes |  |  | Year built (if recorded) |
| `frontage_ft` | REAL | yes |  |  | Frontage on a public street, ft (screen step) |
| `shape_index` | REAL | yes |  |  | Rectangularity 0–1 (screen step) |
| `corner_flag` | BOOLEAN | yes |  |  | Corner lot (screen step) |
| `listing_price` | REAL | yes |  |  | Asking price if listed |
| `listing_source` | TEXT | yes |  |  | Listing source |

### `Buildings`

Building footprints (Overture, which conflates OSM and ML footprints).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `bldg_id` | TEXT | no | yes |  | Building id |
| `area_sqft` | REAL | yes |  |  | Footprint area, ft² |
| `height_m` | REAL | yes |  |  | Height, m |
| `levels` | REAL | yes |  |  | Floors above ground |

## Feature dataset `Demand`

### `DemandAnchors`

Classified demand generators with a size metric (Phase B).

Geometry: Point · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `anchor_id` | TEXT | no | yes |  | Anchor id |
| `category` | TEXT | no |  | `dm_AnchorCategory` | Demand category |
| `name` | TEXT | yes |  |  | Name |
| `size_metric` | TEXT | yes |  | `dm_SizeMetric` | Size unit |
| `size_value` | REAL | yes |  |  | Size in size_metric units |
| `drive_share` | REAL | yes |  | `rg_Occupancy` | Driver mode share 0–1 |
| `venue_id` | TEXT | yes |  |  | Venues.venue_id for venue anchors |

### `TransitStops`

GTFS stops with peak service.

Geometry: Point · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `stop_id` | TEXT | no | yes |  | GTFS stop_id |
| `stop_name` | TEXT | yes |  |  | Stop name |
| `route_count` | INTEGER | yes |  |  | Routes serving the stop |
| `peak_departures` | INTEGER | yes |  |  | Departures in the peak window |
| `peak_headway_min` | REAL | yes |  |  | Peak headway, minutes |
| `high_frequency_flag` | BOOLEAN | yes |  |  | Headway at or below the threshold |

### `Venues`

Event venues with seats and event counts.

Geometry: Point · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `venue_id` | TEXT | no | yes |  | Venue id |
| `name` | TEXT | yes |  |  | Name |
| `seats` | REAL | yes |  |  | Seats |
| `events_per_year` | REAL | yes |  |  | Events per year |
| `event_calendar_source` | TEXT | yes |  |  | Calendar source |

### `Places`

POIs from Overture/OSM, standardized (ADR-0006).

Geometry: Point · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `place_id` | TEXT | no | yes |  | Place id |
| `name` | TEXT | yes |  |  | Name |
| `category` | TEXT | yes |  |  | Normalized category |
| `category_src` | TEXT | yes |  |  | Source category |
| `tags_json` | JSON | yes |  |  | Source tags |

### `BlockJobs`

LODES WAC jobs at census block internal points (ADR-0006).

Geometry: Point · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `block_geoid` | TEXT | no | yes |  | 2020 block GEOID |
| `jobs_total` | REAL | yes |  |  | All jobs (C000) |
| `sectors_json` | JSON | yes |  |  | Jobs by NAICS sector (CNS01–CNS20) |

### `BlockGroups`

ACS 5-year block-group indicators (ADR-0006).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `bg_geoid` | TEXT | no | yes |  | Block group GEOID |
| `population` | REAL | yes |  |  | B01003_001E |
| `workers_total` | REAL | yes |  |  | B08301_001E |
| `workers_drove` | REAL | yes |  |  | B08301_002E |
| `drive_share` | REAL | yes |  |  | workers_drove / workers_total |
| `units_total` | REAL | yes |  |  | B25024_001E |
| `units_5plus` | REAL | yes |  |  | B25024_006E–009E |
| `households` | REAL | yes |  |  | B25044_001E |
| `households_no_vehicle` | REAL | yes |  |  | B25044_003E + 010E |

### `Hospitals`

Hospitals with bed counts (ADR-0006).

Geometry: Point · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `hospital_id` | TEXT | no | yes |  | Hospital id |
| `name` | TEXT | yes |  |  | Name |
| `beds` | REAL | yes |  |  | Beds |

### `Institutions`

Colleges/universities with enrollment (ADR-0006).

Geometry: Point · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `unitid` | TEXT | no | yes |  | IPEDS UNITID |
| `name` | TEXT | yes |  |  | Name |
| `enrollment` | REAL | yes |  |  | 12-month enrollment |

## Feature dataset `Supply`

### `ParkingOSM`

OSM amenity=parking features, standardized (ADR-0006).

Geometry: Geometry · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `osm_id` | TEXT | no | yes |  | OSM type/id |
| `name` | TEXT | yes |  |  | Name |
| `parking` | TEXT | yes |  |  | OSM parking tag (surface, multi-storey, ...) |
| `capacity` | REAL | yes |  |  | Tagged capacity |
| `fee` | TEXT | yes |  |  | OSM fee tag |
| `access` | TEXT | yes |  |  | OSM access tag |
| `operator` | TEXT | yes |  |  | Operator |
| `levels` | REAL | yes |  |  | Levels |
| `area_sqft` | REAL | yes |  |  | Polygon area, ft² |

### `SupplyFacilities`

Merged off-street supply (OSM/Overture/listings/city/manual), one point per facility (ADR-0060).

Geometry: Point · CRS: analysis CRS
 · Subtypes by `type`

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `facility_id` | TEXT | no | yes |  | Facility id |
| `name` | TEXT | yes |  |  | Name |
| `type` | TEXT | no |  | `dm_SupplyType` | Facility type (subtype) |
| `capacity_stated` | REAL | yes |  |  | Published capacity |
| `capacity_est` | REAL | yes |  |  | Estimated capacity |
| `capacity_source` | TEXT | yes |  |  | stated | area | footprint×levels |
| `area_sqft` | REAL | yes |  |  | Footprint area, ft² |
| `fee_flag` | BOOLEAN | yes |  |  | Paid |
| `private_flag` | BOOLEAN | yes |  |  | Private/reserved |
| `rate_hour` | REAL | yes |  |  | Hourly rate |
| `rate_day` | REAL | yes |  |  | Daily rate |
| `rate_month` | REAL | yes |  |  | Monthly rate |
| `rate_event` | REAL | yes |  |  | Event rate |
| `operator` | TEXT | yes |  |  | Operator |

### `OnStreetSegments`

Curb segments with estimated stalls and meter/permit status.

Geometry: LineString · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `segment_id` | TEXT | no | yes |  | Segment id |
| `length_ft` | REAL | yes |  |  | Curb length, ft |
| `stalls_est` | REAL | yes |  |  | length_ft / stall length |
| `metered_flag` | BOOLEAN | yes |  |  | Metered |
| `permit_flag` | BOOLEAN | yes |  |  | Permit-only |
| `rate_hour` | REAL | yes |  |  | Meter rate per hour |

## Feature dataset `Analysis`

### `HotZones`

Contiguous hexes meeting the multi-daypart gap rule (Phase D).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `zone_id` | TEXT | no | yes |  | Hot-zone id |
| `dayparts_positive` | TEXT | yes |  |  | Dayparts with gap > 0, ';'-joined |
| `total_gap_stalls` | REAL | yes |  |  | Sum of positive gap stalls |
| `mean_rate_index` | REAL | yes |  |  | Mean rate index |

### `CandidateParcels`

Every evaluated parcel with its screen result and all failing reasons (Phase E).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `parcel_id` | TEXT | no | yes |  | Parcels.parcel_id |
| `screen_status` | TEXT | no |  | `dm_ScreenStatus` | Pass / Fail / Review |
| `screen_reason` | TEXT | yes |  |  | All failing/review reasons, ';'-joined |
| `walk_min_to_hotzone` | REAL | yes |  |  | Network walk minutes to nearest hot zone |
| `brownfield_flag` | BOOLEAN | yes |  |  | Brownfield within the configured distance |
| `flood_flag` | BOOLEAN | yes |  |  | Intersects SFHA |
| `pipeline_flag` | BOOLEAN | yes |  |  | Active development permit |
| `slope_pct` | REAL | yes |  |  | Mean slope, percent |

### `WalkSheds`

Network walk sheds per candidate (3/5/8 min).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `parcel_id` | TEXT | no |  |  | CandidateParcels.parcel_id |
| `minutes` | INTEGER | no |  |  | Walk minutes |

## Feature dataset `Results`

### `SiteScores`

Criterion raw and scaled values, composite and rank per scenario (Phase G).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `parcel_id` | TEXT | no |  |  | CandidateParcels.parcel_id |
| `scenario` | TEXT | no |  | `dm_Scenario` | Weight scenario |
| `c01_raw` | REAL | yes |  |  | C01 raw |
| `c02_raw` | REAL | yes |  |  | C02 raw |
| `c03_raw` | REAL | yes |  |  | C03 raw |
| `c04_raw` | REAL | yes |  |  | C04 raw |
| `c05_raw` | REAL | yes |  |  | C05 raw |
| `c06_raw` | REAL | yes |  |  | C06 raw |
| `c07_raw` | REAL | yes |  |  | C07 raw |
| `c08_raw` | REAL | yes |  |  | C08 raw |
| `c09_raw` | REAL | yes |  |  | C09 raw |
| `c10_raw` | REAL | yes |  |  | C10 raw |
| `c01_s` | REAL | yes |  | `rg_Score` | C01 scaled 0–100 |
| `c02_s` | REAL | yes |  | `rg_Score` | C02 scaled 0–100 |
| `c03_s` | REAL | yes |  | `rg_Score` | C03 scaled 0–100 |
| `c04_s` | REAL | yes |  | `rg_Score` | C04 scaled 0–100 |
| `c05_s` | REAL | yes |  | `rg_Score` | C05 scaled 0–100 |
| `c06_s` | REAL | yes |  | `rg_Score` | C06 scaled 0–100 |
| `c07_s` | REAL | yes |  | `rg_Score` | C07 scaled 0–100 |
| `c08_s` | REAL | yes |  | `rg_Score` | C08 scaled 0–100 |
| `c09_s` | REAL | yes |  | `rg_Score` | C09 scaled 0–100 |
| `c10_s` | REAL | yes |  | `rg_Score` | C10 scaled 0–100 |
| `composite` | REAL | yes |  | `rg_Score` | Weighted composite 0–100 |
| `rank` | INTEGER | yes |  |  | Rank within scenario (tie-break parcel_id) |

### `SiteFinancials`

Pro forma per candidate and tenure (Phase H).

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `parcel_id` | TEXT | no |  |  | CandidateParcels.parcel_id |
| `tenure` | TEXT | no |  | `dm_Tenure` | Buy or ground lease |
| `stalls` | REAL | yes |  |  | Stalls |
| `land_cost` | REAL | yes |  |  | Land cost |
| `construction_cost` | REAL | yes |  |  | Construction cost |
| `soft_cost` | REAL | yes |  |  | Soft cost |
| `total_cost` | REAL | yes |  |  | Total cost |
| `occ_wd_day` | REAL | yes |  | `rg_Occupancy` | Occupancy, weekday day |
| `occ_wd_eve` | REAL | yes |  | `rg_Occupancy` | Occupancy, weekday evening |
| `occ_we_day` | REAL | yes |  | `rg_Occupancy` | Occupancy, weekend day |
| `occ_we_eve` | REAL | yes |  | `rg_Occupancy` | Occupancy, weekend evening |
| `occ_event` | REAL | yes |  | `rg_Occupancy` | Occupancy, event |
| `rate_wd_day` | REAL | yes |  |  | Rate, weekday day |
| `rate_wd_eve` | REAL | yes |  |  | Rate, weekday evening |
| `rate_we_day` | REAL | yes |  |  | Rate, weekend day |
| `rate_we_eve` | REAL | yes |  |  | Rate, weekend evening |
| `rate_event` | REAL | yes |  |  | Rate, event |
| `annual_revenue` | REAL | yes |  |  | Annual revenue |
| `opex` | REAL | yes |  |  | Operating expenses |
| `noi` | REAL | yes |  |  | Net operating income |
| `yield_on_cost` | REAL | yes |  |  | NOI / total cost |
| `value_at_cap` | REAL | yes |  |  | NOI / cap rate |
| `payback_years` | REAL | yes |  |  | Simple payback, years |
| `irr_10yr` | REAL | yes |  |  | 10-year unlevered IRR |
| `npv` | REAL | yes |  |  | NPV at the discount rate |
| `sensitivity_json` | JSON | yes |  |  | Sensitivity results |

### `Shortlist`

Final ranked shortlist with recommendation and due-diligence flags.

Geometry: MultiPolygon · CRS: analysis CRS

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `parcel_id` | TEXT | no | yes |  | CandidateParcels.parcel_id |
| `final_rank` | INTEGER | yes |  |  | 0.70 financial + 0.30 suitability rank |
| `recommended_flag` | BOOLEAN | yes |  |  | Recommended site |
| `alternate_flag` | BOOLEAN | yes |  |  | Alternate site |
| `profile_page_no` | INTEGER | yes |  |  | Page in the map series |
| `due_diligence_flags` | TEXT | yes |  |  | Flags, ';'-joined |
| `notes` | TEXT | yes |  |  | Notes |

## Standalone tables

### `DataSourceRegistry`

Provenance: one row per source per run.

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `source_id` | TEXT | no |  |  | Source id |
| `run_id` | TEXT | no |  |  | Run id |
| `provider` | TEXT | yes |  |  | Provider |
| `dataset` | TEXT | yes |  |  | Dataset |
| `endpoint` | TEXT | yes |  |  | URL or local path (secrets redacted) |
| `vintage` | TEXT | yes |  |  | Data vintage |
| `download_date` | TEXT | yes |  |  | Date fetched/loaded |
| `license` | TEXT | yes |  |  | Licence ([VERIFY] if unconfirmed) |
| `native_crs` | TEXT | yes |  |  | CRS as delivered |
| `transformation` | TEXT | yes |  |  | CRS transformation applied |
| `row_count` | INTEGER | yes |  |  | Rows written |
| `status` | TEXT | yes |  |  | loaded | not configured | failed |
| `notes` | TEXT | yes |  |  | Notes |

### `QAQC_Log`

QA check results.

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `check_id` | TEXT | no |  |  | Check id |
| `run_id` | TEXT | no |  |  | Run id |
| `step` | TEXT | yes |  |  | Step |
| `layer` | TEXT | yes |  |  | Layer checked |
| `check_name` | TEXT | yes |  |  | Check |
| `result` | TEXT | yes |  |  | Result text |
| `count` | REAL | yes |  |  | Measured value |
| `threshold` | TEXT | yes |  |  | Threshold |
| `passed` | BOOLEAN | yes |  |  | Passed |
| `severity` | TEXT | yes |  |  | error | warning | info |
| `timestamp` | DATETIME | yes |  |  | UTC time |

### `ScoreRuns`

Run log: one row per step per run.

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no |  |  | Run id |
| `market` | TEXT | yes |  |  | Market slug |
| `scenario` | TEXT | yes |  | `dm_Scenario` | Scenario (scoring steps) |
| `step` | TEXT | yes |  |  | Step |
| `timestamp` | DATETIME | yes |  |  | UTC time |
| `toolbox_version` | TEXT | yes |  |  | parkiq version |
| `git_commit` | TEXT | yes |  |  | Git commit |
| `params_json` | JSON | yes |  |  | Resolved parameters |
| `candidate_cnt` | INTEGER | yes |  |  | Pass candidates |

### `ParkingRates`

Generation rates by category and daypart.

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no |  |  | Run id |
| `category` | TEXT | yes |  |  | Rate category |
| `daypart` | TEXT | yes |  | `dm_Daypart` | Daypart |
| `rate` | REAL | yes |  |  | Stalls per unit |
| `unit` | TEXT | yes |  |  | Unit |
| `source_citation` | TEXT | yes |  |  | Citation |
| `calibration_factor` | REAL | yes |  |  | Pilot calibration factor |

### `CriteriaDefinitions`

Scoring criteria C01–C10.

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no |  |  | Run id |
| `criterion_id` | TEXT | yes |  |  | C01–C10 |
| `name` | TEXT | yes |  |  | Name |
| `description` | TEXT | yes |  |  | Description |
| `unit` | TEXT | yes |  |  | Unit |
| `direction` | TEXT | yes |  | `dm_Direction` | Benefit or Cost |
| `normalization` | TEXT | yes |  |  | Normalization rule |

### `WeightScenarios`

Weights per scenario and criterion.

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no |  |  | Run id |
| `scenario` | TEXT | yes |  | `dm_Scenario` | Scenario |
| `criterion_id` | TEXT | yes |  |  | CriteriaDefinitions.criterion_id |
| `weight` | REAL | yes |  |  | Weight (sums to 1 per scenario) |

### `FinanceParams`

Resolved finance parameters per run.

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no |  |  | Run id |
| `param` | TEXT | yes |  |  | Parameter |
| `value` | TEXT | yes |  |  | JSON value |

### `Validation`

Pilot back-test: observed vs modeled (Phase I).

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no |  |  | Run id |
| `facility_id` | TEXT | yes |  |  | SupplyFacilities.facility_id |
| `observed_metric` | TEXT | yes |  |  | What was observed |
| `observed_value` | REAL | yes |  |  | Observed |
| `modeled_value` | REAL | yes |  |  | Modeled |
| `error_pct` | REAL | yes |  |  | (modeled − observed) / observed × 100 |

### `Hex_Demand_Daypart`

Modeled demand stalls per hex and daypart (Phase B).

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no |  |  | Run id |
| `hex_id` | TEXT | no |  |  | HexGrid.hex_id |
| `daypart` | TEXT | no |  | `dm_Daypart` | Daypart |
| `demand_stalls` | REAL | yes |  |  | Demand, stalls |
| `components_json` | JSON | yes |  |  | Contribution by anchor category |
| `method` | TEXT | yes |  |  | Model version/method |

### `Hex_Supply_Daypart`

Supply stalls per hex and daypart (Phase C).

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no |  |  | Run id |
| `hex_id` | TEXT | no |  |  | HexGrid.hex_id |
| `daypart` | TEXT | no |  | `dm_Daypart` | Daypart |
| `supply_stalls` | REAL | yes |  |  | Supply, stalls |
| `effective_supply_stalls` | REAL | yes |  |  | Supply with private share applied |

### `Hex_Gap_Daypart`

Demand − effective supply per hex and daypart (Phase D).

Geometry: table · CRS: —

| Field | Type | Null | Unique | Domain | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no |  |  | Run id |
| `hex_id` | TEXT | no |  |  | HexGrid.hex_id |
| `daypart` | TEXT | no |  | `dm_Daypart` | Daypart |
| `gap_stalls` | REAL | yes |  |  | demand − effective supply |
| `gap_ratio` | REAL | yes |  |  | demand / supply |
| `rate_index` | REAL | yes |  |  | Normalized achievable rate |

## Rasters

| Raster | Dataset | File | Units | Description |
|---|---|---|---|---|
| `Slope_pct` | Reference | `rasters/Slope_pct.tif` | percent rise | Percent slope from the 3DEP DEM (Horn). |
| `RateSurface_{daypart}` | Supply | `rasters/RateSurface_{daypart}.tif` | currency per hour | IDW achievable-rate surface, one per daypart. |

## Raw snapshots

Immutable, EPSG:4326, source attributes as delivered: `Raw_Boundary`, `Raw_Parcels`, `Raw_Buildings`, `Raw_Places_Overture`, `Raw_OSM_POI`, `Raw_OSM_Parking`, `Raw_LODES_WAC`, `Raw_ACS_BG`, `Raw_GTFS_Stops`, `Raw_Venues`, `Raw_Hospitals`, `Raw_Institutions`, `Raw_AADT`, `Raw_FEMA_NFHL`, `Raw_EPA_Sites`, `Raw_Zoning`, `Raw_ZoningOverlays`, `Raw_ParkingZones`, `Raw_OnStreet`.

## Relationship classes

| Name | Origin | Destination | Cardinality | Keys | Note |
|---|---|---|---|---|---|
| CandidateParcels_SiteScores | `CandidateParcels` | SiteScores | 1:M | `parcel_id` → `parcel_id` |  |
| CandidateParcels_SiteFinancials | `CandidateParcels` | SiteFinancials | 1:1 | `parcel_id` → `parcel_id` | one row per tenure (Buy, Lease) |
| CandidateParcels_WalkSheds | `CandidateParcels` | WalkSheds | 1:M | `parcel_id` → `parcel_id` |  |
| ScoreRuns_SiteScores | `ScoreRuns` | SiteScores | 1:M | `run_id` → `run_id` |  |
| CriteriaDefinitions_WeightScenarios | `CriteriaDefinitions` | WeightScenarios | 1:M | `criterion_id` → `criterion_id` |  |
| DataSourceRegistry_Sources | `DataSourceRegistry` | every source-derived feature class | 1:M | `source_id` → `source_id` | every source-derived feature class |
| Venues_DemandAnchors | `Venues` | DemandAnchors | 1:M | `venue_id` → `venue_id` |  |
| Parcels_CandidateParcels | `Parcels` | CandidateParcels | 1:1 | `parcel_id` → `parcel_id` | addition |
| HexGrid_HexDemand | `HexGrid` | Hex_Demand_Daypart | 1:M | `hex_id` → `hex_id` | addition |
| HexGrid_HexSupply | `HexGrid` | Hex_Supply_Daypart | 1:M | `hex_id` → `hex_id` | addition |
| HexGrid_HexGap | `HexGrid` | Hex_Gap_Daypart | 1:M | `hex_id` → `hex_id` | addition |

## Rules

- topology: `Parcels` — must not overlap (tolerance 0.1 ft)
- topology: `HexGrid` — must not overlap or have gaps
- attribute: `Parcels`.lot_sqft — = Shape_Area (market units)
- attribute: `Parcels`.improvement_value_ratio — assessed_improvement_value / NULLIF(assessed_land_value, 0)
- attribute: `SiteScores`.composite — BETWEEN 0 AND 100 (rg_Score)
- attribute: `SiteFinancials`.occ_* — BETWEEN 0 AND 1 (rg_Occupancy)
