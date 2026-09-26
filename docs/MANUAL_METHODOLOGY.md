# ParkIQ: Manual Methodology (Desktop GIS + Excel)

**Purpose:** Complete the surface-lot parking site-selection and investment analysis for one market **by hand**, step by step, using ArcGIS Pro (or QGIS) and Excel, following the method in `docs/SCOPE.md`.
**Relationship to the toolkit:** This is the same method the ParkIQ code will automate. Your manual run of the first market becomes the reference result the code must reproduce.
**Status of numbers:** Every rate, cost and threshold below is either a scope placeholder tagged **[VERIFY]** or a blank you must fill. Numeric examples are **illustrative arithmetic only**, not recommendations.

---

## Contents

0. How to use this document
1. Before you start: software, scale, effort
2. Project setup: folders, database, logs
3. The parameter sheet (fill before any analysis)
4. Phase A, Market setup (boundary, grid, network, slope)
5. Phase A2, Data acquisition and ingest QA
6. Phase B, Demand model
7. Phase C, Supply inventory and rates
8. Phase D, Gap analysis and hot zones
9. Phase E, Candidate parcel screen
10. Phase F, Network metrics for candidates
11. Phase G, Criteria, scoring, scenarios, sensitivity
12. Phase H, Financial model (Excel)
13. Phase I, Final ranking and shortlist
14. Phase J, Due-diligence flags
15. Phase K, Validation and calibration (pilot market)
16. QA/QC checklist
17. Outputs: maps, dashboard, memo, StoryMap
18. Repeating for the next market
- Appendices A–G: field lists, LODES sector mapping, Excel layouts, formula reference, templates

---

## 0. How to use this document

- Work phases in order; each phase lists **Inputs → Steps → Output layer/table → Checks**.
- Tool names are given for **ArcGIS Pro** first, then **QGIS** in brackets. Verify exact tool names in your software version.
- Whenever you make a choice the scope leaves open, write it in the **Decision Log** (Appendix F) before moving on. Whenever you use a number you haven't confirmed, tag it `[VERIFY]` in the Parameter Sheet.
- Keep one **Source Register** row per dataset (Appendix F) as you download it.
- Name every output with the run ID: `YYYYMMDD_HHMM_<market>_<scenario>`, e.g. `20261001_0900_examplecity_Balanced`.

---

## 1. Before you start

### 1.1 Software

| Need | ArcGIS Pro | QGIS alternative |
|---|---|---|
| Core GIS | ArcGIS Pro 3.x (Standard/Advanced helpful for some tools) | QGIS 3.x LTR |
| Raster (slope, IDW) | Spatial Analyst extension | Built-in raster tools |
| Walk-time network | Network Analyst extension + a network dataset (built from OSM streets, or StreetMap Premium if licensed) | **QNEAT3** plugin (OD matrix) and built-in *Network analysis* tools |
| H3 hexagons | *Generate Tessellation* with H3 shape (Pro 3.1+) [VERIFY in your version] | An H3 plugin [VERIFY], or regular hexagons of equal area (see 4.2) |
| OSM download | Download extract from Geofabrik | **QuickOSM** plugin or Geofabrik |
| Transit frequency | *Calculate Transit Service Frequency* (Public Transit toolset) [VERIFY availability] | GTFS plugin, or Excel pivot of `stop_times.txt` |
| Spreadsheet | Excel 365 (dynamic arrays needed for the sensitivity sheet) | Same |

**No Network Analyst?** Use QGIS + QNEAT3 for Phases B, C and F only, and bring the resulting tables back into Pro. That is fully acceptable.

### 1.2 Scale guidance

A manual run is realistic for a downtown or submarket of roughly **5–30 km²**, a few hundred to a few thousand anchors, and 40–200 candidate parcels. For a whole county, either:

- restrict the study area to focus submarkets, or
- aggregate small anchors to hex centroids before network allocation (see 6.5).

Record whichever you choose in the Decision Log.

### 1.3 Rough effort (first market, one analyst; estimate only)

| Phase | Days |
|---|---|
| Setup, parameters, data download | 2–3 |
| Demand + supply + gap | 3–4 |
| Screen + network metrics + scoring + sensitivity | 2–3 |
| Financial model + shortlist | 2–3 |
| Maps, memo, QA | 2–3 |

Later markets go faster because the Excel workbooks and map layouts are reused.

---

## 2. Project setup

### 2.1 Folder structure

```
ParkIQ_<market>/
├── 00_admin/        Parameter_Sheet.xlsx, Decision_Log.xlsx, Source_Register.xlsx, QA_Log.xlsx
├── 01_raw/          one subfolder per source ID (S01_parcels, S04_lodes …); never edit files here
├── 02_working/      ParkIQ_<market>.gdb (or .gpkg), scratch.gdb
├── 03_tables/       exported CSV/XLSX tables for Excel steps
├── 04_excel/        Scoring.xlsx, Financial_Model.xlsx, Sensitivity.xlsx
├── 05_maps/         map PDFs/PNGs, map series
├── 06_package/      memo, dashboard, final GeoPackage
└── ParkIQ_<market>.aprx
```

### 2.2 Geodatabase

Create `ParkIQ_<market>.gdb` with feature datasets `Raw`, `Reference`, `Cadastral`, `Demand`, `Supply`, `Analysis`, `Results`, all in your **analysis CRS**.

- The analysis CRS should be the local State Plane zone (US feet) or UTM zone (meters).
- Record whether its units are feet or meters. Every distance below must be converted to those units.
- Optional: create the coded-value domains from SCOPE §4.4 (e.g. `dm_ScreenStatus`, `dm_Daypart`). They prevent typos in category fields.

Every feature class you create gets three fields:

- `source_id` (text)
- `run_id` (text)
- `load_ts` (date)

### 2.3 Unit conversions you'll use constantly

| Quantity | Value |
|---|---|
| Walking speed 1.3 m/s [PARAMETER] | 78 m/min = 255.9 ft/min |
| 3 / 5 / 8 minutes at 78 m/min | 234 / 390 / 624 m (768 / 1,280 / 2,047 ft) |
| 1 mile study buffer | 1,609.34 m |
| 1 m² | 10.7639 ft² |
| 1 km² | 247.1 acres = 10,763,910 ft² |

---

## 3. The parameter sheet

Build `Parameter_Sheet.xlsx` **before** any analysis.

- Columns: `group, parameter, value, unit, status (PARAMETER / VERIFY / set), source/citation, notes`.
- Values below come from SCOPE §2.1 and appendices.
- **Blank = you must decide.** Do not proceed with a blank that a later step needs.

### 3.1 Site and screen

| Parameter | Scope value | Notes |
|---|---|---|
| min_parcel_sqft | 15,000 | Yields ~39 stalls at the defaults below, which is below 50. See 9.3. |
| max_parcel_sqft | 200,000 | Yields ~518 stalls, which is above 300. |
| target_stalls_range | 50–300 | |
| stall_area_sqft_gross | 320 | [PARAMETER] Typical range 300–350. |
| layout_efficiency | 0.90 | |
| setback_landscape_pct | 0.08 | |
| max_slope_pct | 5 | |
| min_frontage_ft | 60 | |
| min_shape_index | 0.60 | Depends on the metric chosen in 9.2. |
| improvement_ratio_max | 0.25 | Threshold for a low-value improvement. |
| frontage_buffer | *blank* | How far from a street centerline a parcel edge counts as frontage. |

### 3.2 Demand

| Parameter | Scope value | Notes |
|---|---|---|
| walk_shed_minutes | 3, 5, 8 | |
| decay_weights | 1.0 / 0.6 / 0.25 | Weights for ≤3 / 3–5 / 5–8 minutes. |
| walking_speed | 1.3 m/s | [PARAMETER][VERIFY] |
| transit high_frequency_radius | 400 m | |
| transit demand_factor | 0.85 | [VERIFY] |
| high-frequency definition (peak headway ≤ X min) | *blank* | |
| rate_source_baseline_drive_share | *blank* | See 6.3. |
| residential offstreet_share | *blank* | See 6.2. |
| Parking-generation rates | Appendix C table (copy into sheet) | Every row [VERIFY]. |

### 3.3 Supply

| Parameter | Scope value | Notes |
|---|---|---|
| private_effective_share | 0.50 | |
| onstreet_stall_length_ft | 22 | |
| on-street intersection clearance / driveway allowance | *blank* | |
| dedupe distance | 40 m | |

### 3.4 Finance

| Parameter | Scope value | Notes |
|---|---|---|
| assessed_to_market_ratio | 1.20 | [VERIFY] Calibrate per market. |
| construction_cost_per_stall_usd | 6,500 | [VERIFY regional] |
| soft_cost_pct | 0.15 | Record the base it applies to (see 12.4). |
| opex_per_stall_year_usd | 450 | [VERIFY] |
| payment/tech fee % of revenue | *blank* | |
| management fee % of revenue | *blank* | |
| property_tax_rate | 0.012 | [VERIFY] |
| new_entrant_rate_discount | 0.10 | |
| occupancy caps | wd_day 0.85, wd_eve 0.60, we_day 0.40, we_eve 0.70, event 0.90 | |
| occupancy curve breakpoints | *blank* | See 12.2. |
| capture_share | *blank* | See 12.2. |
| billing basis + billable hours / turns per daypart | *blank* | |
| operating days per year per daypart | *blank* | |
| event weekday/weekend split | *blank* | |
| permit_share / office-heavy threshold | *blank* | |
| revenue growth, opex growth | *blank* | |
| exit cap rate, selling costs % | *blank* | Exit cap defaults to the target cap rate if you choose. |
| ground-lease rent % of land value, escalator, lease term | *blank* | |
| target_cap_rate | 0.075 | |
| hold_years | 10 | |
| discount_rate | 0.12 | |

### 3.5 Ranking

| Parameter | Scope value |
|---|---|
| financial_weight / suitability_weight | 0.70 / 0.30 |
| Scenario weights | Appendix B (Balanced, DemandFirst, CostFirst) |
| Shortlist size | 5–10 |

---

## 4. Phase A: Market setup

### 4.1 Boundary and study area

1. Download the boundary.
   - Place or county: from Census TIGER/Line.
   - Custom: digitize or import it.
2. **Project** it to the analysis CRS → `Reference/MarketBoundary`.
3. **Calculate Geometry Attributes** → `area_sqmi`.
4. **Buffer** the boundary by 1 mile → `Reference/StudyArea`. This is the clip extent for every source.
5. Optional: digitize focus submarkets → `Reference/Submarkets` (`name`, `type`). These are used only for reporting and map insets, never as filters.

### 4.2 Analysis grid (H3 resolution 9)

1. **Generate Tessellation**
   - Shape type: H3 hexagon, resolution 9.
   - Extent: `StudyArea`.
   - Output: `Reference/HexGrid`.
2. Keep hexes whose centroid falls in `StudyArea`.
3. Add fields:
   - `hex_id` (the H3 index the tool writes)
   - `area_km2`
   - `submarket` (via Spatial Join to Submarkets, largest overlap)
4. **Feature To Point** (inside) → `HexCentroids`. Allocation uses centroids.

**If you can't generate true H3:** use regular hexagons of equal area.

- H3 r9 average area is about **0.105 km²**, which is a regular-hexagon side of about **201 m**.
- Log this in the Decision Log. The results are equivalent for a manual run, but hex IDs won't match the toolkit's.

### 4.3 Pedestrian network

1. Download OSM streets for `StudyArea` (Geofabrik extract or QuickOSM).
2. Keep walkable ways.
   - Drop motorway, motorway_link, trunk_link, and ways tagged `foot=no` or `access=private`.
   - Keep footway, path, pedestrian, steps, residential, service, primary/secondary/tertiary, living_street.
3. **Project** to the analysis CRS. Planarize/split at intersections: *Feature To Line* [QGIS: *Split with lines*].
4. Add fields:
   - `length_m`
   - `walk_minutes = length_m / 78` (walking speed from the Parameter Sheet)
5. Build the network:
   - **Pro:** create a network dataset in a feature dataset. Cost attribute = `walk_minutes`, no one-way restrictions, connectivity at endpoints.
   - **QGIS:** no build step; QNEAT3 uses the line layer with `walk_minutes` as cost.
6. Test it: solve one service area of 5 minutes from a downtown point. Check visually that it follows streets and does not jump rivers or highways.
7. Save as `Reference/WalkEdges` (+ `WalkNodes` if your tool creates junctions).

### 4.4 Slope

1. Download the USGS 3DEP 1/3 arc-second (~10 m) DEM for `StudyArea` from The National Map.
2. **Project Raster** to the analysis CRS (bilinear resampling).
3. **Slope**, output measurement = **Percent rise** → `Slope_pct`.
   - QGIS gives degrees. Convert: `pct = tan(radians(deg)) × 100`.
   - If the CRS is in feet and the DEM in meters, set the Z-factor to 3.2808 (Pro).

---

## 5. Phase A2: Data acquisition and ingest QA

### 5.1 What to download (clip everything to `StudyArea`)

| ID | Get | From (confirm current access [VERIFY]) | Save to |
|---|---|---|---|
| S01 | Parcels + assessed land/improvement values, land use, zoning | Regrid (if licensed) or county GIS/assessor open data | `Cadastral/Parcels` |
| S02 | Building footprints (+ height/levels) | Overture Maps (buildings theme) | `Cadastral/Buildings` |
| S03 | POIs | Overture Places; OSM | `Raw/POI` |
| S04 | Jobs by census block (WAC, all jobs, JT00) | LEHD LODES (lehd.ces.census.gov), latest year for your state | `Raw/LODES_WAC` + block polygons (TIGER) |
| S05 | ACS 5-yr block group tables: means of transportation to work (B08301), tenure by vehicles available (B25044), units in structure (B25024) [VERIFY table IDs] | data.census.gov / Census API + TIGER block groups | `Raw/ACS_BG` |
| S06 | Existing parking | OSM `amenity=parking` (with `parking=surface/multi-storey/street_side`, `capacity`, `fee`); Overture parking POIs | `Raw/Parking_OSM` |
| S07 | Listed parking rates | SpotHero/ParkWhiz/ParkMobile **only if your access and their terms allow** [VERIFY]; otherwise your own field/phone/signage survey | `Raw/Rates_Observed` |
| S09 | GTFS | Transit agency or Mobility Database | `01_raw/S09_gtfs/` |
| S10 | Venues (seats) + events/year | OSM/Overture venues; venue websites; Ticketmaster (API terms [VERIFY]) | `Demand/Venues` |
| S11 | Hotels (+ rooms) | OSM/Overture; hotel websites for room counts | `Raw/Hotels` |
| S12 | Hospitals (beds); universities (enrollment) | HIFLD hospitals [VERIFY current availability] or CMS provider data; IPEDS (nces.ed.gov/ipeds) | `Raw/Hospitals`, `Raw/Universities` |
| S13 | AADT | State DOT traffic counts or FHWA HPMS | `Raw/AADT` |
| S14 | Flood zones | FEMA NFHL (msc.fema.gov) | `Raw/NFHL_FldHaz` |
| S15 | Brownfields / regulated sites | EPA FRS; EPA ACRES / Cleanups in My Community | `Raw/EPA_Sites` |
| S16 | Land listings (asking price, size) | LoopNet/Crexi/CoStar per their terms [VERIFY] | `Raw/LandListings` |
| S18 | DEM | USGS 3DEP | done in 4.4 |
| S20–S24 | Meters, citations, permits, zoning, parking studies | City open-data portal | `Raw/City_*` |

After each download, add a row to the **Source Register**:

- `source_id, provider, dataset, url/endpoint, vintage, download_date, license, native_crs, transformation, notes`

### 5.2 Ingest procedure (for every layer)

1. Copy the original, untouched, to the `Raw` feature dataset (or `01_raw/`).
2. **Project** to the analysis CRS. Note the transformation used in the Source Register.
3. **Clip** to `StudyArea`.
4. **Repair Geometry** [QGIS: *Fix geometries*]. Delete features that are still null.
5. **Find Identical** on the ID field (and shape). Resolve duplicates.
6. Add `source_id`, `run_id`, `load_ts`.

### 5.3 Parcels: required fields

Compute or populate these in `Cadastral/Parcels`:

| Field | How |
|---|---|
| `lot_sqft` | *Calculate Geometry* area in US square feet |
| `assessed_land_value`, `assessed_improvement_value` | Assessor attributes |
| `improvement_value_ratio` | `improvement / land` (null if land = 0) |
| `land_use_class` | Crosswalk county land-use codes → Vacant / SurfaceParking / Commercial / Industrial / Residential / MixedUse / Institutional / Other. Save the crosswalk table (Appendix F), it is market-specific. |
| `owner_type` | Classify owner names: Public (city/county/state/authority), Institutional (university/hospital/church), Corporate (LLC/INC/CORP), Private (individuals), Unknown |
| `zoning_code`, `zoning_screen` | Read the zoning ordinance use table for "commercial parking lot / principal-use parking". Tag each zone as ByRight, Conditional (special/conditional use permit) or Prohibited. Unmatched zones are Unknown. Save as a table and join. |
| `listing_price`, `listing_source` | Spatial join from land listings, where present |

**Tip, surface lots:** Overlay OSM surface-parking polygons on parcels. A parcel ≥ 50% covered by a surface lot with no building gets `land_use_class = SurfaceParking` if the assessor code doesn't already say so. Record this rule.

### 5.4 Ingest QA (log in `QA_Log.xlsx`)

| Check | Pass condition |
|---|---|
| All layers in the analysis CRS | 100% |
| All features within `StudyArea` | 100% |
| Null/invalid geometry after repair | 0 |
| Duplicate `parcel_id` / `facility_id` | 0 |

---

## 6. Phase B: Demand model (hex × daypart)

The five dayparts are:

- `wd_day`: weekday day
- `wd_eve`: weekday evening
- `we_day`: weekend day
- `we_eve`: weekend evening
- `event`: event day

### 6.1 Build the `DemandAnchors` point layer

Merge the following into one point layer `Demand/DemandAnchors`:

| Category | Source | Size metric | `size_value` |
|---|---|---|---|
| Office | LODES WAC office-type sectors (Appendix B) at block centroid | Jobs | Sum of office sectors |
| Other employment | Remaining LODES sectors, only if you have a rate for them | Jobs | Sum |
| Medical | Hospitals | Beds | Licensed/staffed beds |
| University | IPEDS | Enrollment | Total enrollment. Place the point at the main campus core; move it manually if the IPEDS point is off-campus. |
| Hotel | Hotels | Rooms | Room count (from website if untagged) |
| RestaurantBar | Overture/OSM restaurants, bars, cafés | Sqft | Building footprint area × levels if the POI is alone in its building; otherwise record your rule, e.g. a typical-sqft-per-POI parameter [blank] |
| Retail | Overture/OSM shops | Sqft | Same rule |
| Venue | Venues | Seats | Seats. Also fill `events_per_year`. |
| ResidentialBlock | ACS block-group centroid | Units | See 6.2 |

Also fill `anchor_id`, `category`, `name`, `size_metric`, `size_value`, `source_id` for each anchor.

**Avoid double counting:** hospital and university jobs appear in LODES too.

- Either remove LODES health/education sectors in blocks containing a hospital/university anchor, or
- use jobs only and skip the beds/enrollment rate for staff.

Pick one and log it.

**Top-50 review (required QA):** sort anchors by `size_value` within category and eyeball the top 50 on imagery. Fix mislocated or duplicated anchors.

### 6.2 Residential demand input

ACS has no direct count of units without off-street parking, so this is an explicit assumption:

```
units_no_offstreet = units_in_5plus_unit_structures × (1 − offstreet_share)
```

Set `offstreet_share` in the Parameter Sheet and log it as an assumption. If you can't defend a value, set residential demand to zero and say so in the memo.

### 6.3 Generate stalls per anchor per daypart

In the anchor attribute table (or export to Excel), add fields `dem_wd_day, dem_wd_eve, dem_we_day, dem_we_eve, dem_event`:

```
dem_d = size_value_in_rate_units × rate[category][d] × calibration[category] × mode_adj × transit_adj
```

**Rate units:**

- restaurant/retail rates are per 1,000 sqft, so use `size_value / 1000`
- venue rate is per seat on event days only

**`calibration`:** 1.0 until Phase K.

**`mode_adj`:** a method choice; log it.

- Published rates (e.g. ITE) are observed parked cars and already reflect their survey sites' share of people who drive.
- The recommended form is `local_drive_share ÷ rate_source_baseline_drive_share`.
  - Local drive share = drove alone + carpool from ACS B08301 for the block group (or county place-of-work data for jobs).
  - If the baseline is unknown, set `mode_adj = 1` and state that demand is uncorrected for mode.
- Do not multiply by raw local drive share alone; that double-discounts.

**`transit_adj`:** 0.85 if the anchor is within 400 m of a high-frequency stop, else 1.0. To find high-frequency stops:

1. From GTFS, count weekday departures per stop between 07:00 and 09:00.
   - Use *Calculate Transit Service Frequency*, or in Excel: join `stop_times` → `trips` → `calendar` (weekday service), filter the time window, and pivot on `stop_id`.
2. Compute `peak_headway_min = 120 / departures`.
3. `high_frequency_flag = headway ≤ threshold`.
4. **Buffer** flagged stops by 400 m and **Select By Location** anchors inside them.

Save the stops as `Demand/TransitStops` (`stop_id, route_count, peak_headway_min, high_frequency_flag`).

**Venue check:** with the placeholder 0.33 stalls/seat, a 10,000-seat arena generates 3,300 event stalls. The 0.33 comes from 0.85 drive share ÷ 2.6 persons per car [VERIFY both].

### 6.4 Network travel times: anchors → hex centroids

1. **OD Cost Matrix** (Pro: *Make OD Cost Matrix Analysis Layer*; QGIS: QNEAT3 *OD Matrix from Layers as Table (m:n)*):
   - Origins = `DemandAnchors`
   - Destinations = `HexCentroids`
   - Impedance = `walk_minutes`
   - **Cutoff = 8 minutes**
   - No limit on destinations
2. Export the result to `03_tables/OD_anchor_hex.csv` with `anchor_id, hex_id, minutes`.
   - Points far from any street snap to the network. If the snap distance is large (> 100 m), add `snap_distance / 78` to `minutes`. Log it.
3. Assign the band weight:
   - `≤3 → 1.0`
   - `>3 and ≤5 → 0.6`
   - `>5 and ≤8 → 0.25`
4. **Anchors with no hex within 8 minutes** (off-network): assign all demand to the hex containing the anchor. Log the count.

### 6.5 Allocate demand to hexes (demand-conserving)

Each anchor's demand is split across the hexes within its 8-minute walk, in proportion to the band weights. The weights are normalized so the anchor's total is preserved.

1. **Summary Statistics** on the OD table: `SUM(weight)` by `anchor_id` → `w_sum`.
2. Join `w_sum` back to the OD table: `share = weight / w_sum`.
3. Join anchor demand fields to the OD table and compute `alloc_d = dem_d × share` for each daypart.
4. **Summary Statistics:** `SUM(alloc_d)` by `hex_id` (and by `hex_id, category` for the components) → `Analysis/Hex_Demand_Daypart`.
   - Store it long: one row per `hex_id, daypart`, with `demand_stalls, components_json, method`.
   - Or store it wide (one column per daypart) and document the choice.
   - `components_json` by hand: keep the by-category summary table and reference it. That is your audit trail.

**Worked example (illustrative arithmetic):** an anchor has 100 stalls of demand.

| Band | Hexes | Weight each | Share each | Stalls each | Stalls total |
|---|---|---|---|---|---|
| ≤3 min | 1 | 1.0 | 1.0 / 4.3 = 0.2326 | 23.26 | 23.26 |
| 3–5 min | 3 | 0.6 | 0.6 / 4.3 = 0.1395 | 13.95 | 41.86 |
| 5–8 min | 6 | 0.25 | 0.25 / 4.3 = 0.0581 | 5.81 | 34.88 |

- `w_sum = 1(1.0) + 3(0.6) + 6(0.25) = 4.3`
- Total = 100.00 stalls, so demand is conserved.

**Check:** the total of `Hex_Demand_Daypart` for each daypart equals the total of anchor demand (to rounding).

**Scaling shortcut:** for hundreds of small restaurants and shops, first **Spatial Join** them to hexes and sum demand per hex. Then treat each hex centroid as one aggregated anchor. This cuts OD matrix size dramatically; log it.

### 6.6 Demand QA

- Map each daypart. Downtown weekday day should dominate `wd_day`; entertainment districts should dominate evenings.
- If a published parking study exists for the downtown, compare weekday peak demand. The target is ±25%; report the difference either way.

---

## 7. Phase C: Supply inventory and rates

### 7.1 Merge facilities

1. Merge OSM parking, Overture parking, rate-survey/listing points and city inventories → `Supply/SupplyFacilities_merge`.
   - Convert polygons to points for matching, but keep the polygon area.
2. **Generate Near Table** within 40 m (same layer, closest-N) → candidate duplicate pairs.
3. Review the pairs in a table. They are the same facility if the names match (ignoring case/punctuation/"parking"/"lot") or one name is missing.
4. Keep one record per facility using this priority:
   - Capacity: stated > listing > OSM > Overture.
   - Rates: survey/listing.
5. Fill fields:
   - `type`: Surface / Garage / OnStreet / Mixed
   - `fee_flag`
   - `private_flag` (customer-only, residents-only or `access=private` → 1)
   - `operator`

### 7.2 Capacity

| Case | `capacity_est` | `capacity_source` |
|---|---|---|
| `capacity` tag or listing present | Stated value (also compute the estimate for QA) | stated |
| Surface lot polygon | `area_sqft / stall_area_sqft_gross × layout_efficiency` | area |
| Garage | `footprint_sqft × levels / stall_area_sqft_gross`. Levels come from OSM `building:levels`/`parking:levels` or a site check. | footprint |
| Surface lot as a point only | Digitize the polygon from imagery, or flag and exclude | n/a |

**QA:** on facilities with stated capacity, `|estimated − stated| / stated`. Target: median ≤ 20%. If it's worse, revisit the stall area or efficiency for this market (log it).

### 7.3 On-street supply (`Supply/OnStreetSegments`)

- If the city publishes meter or block-face data (S20), use it directly.
- Otherwise, from the drive-street network (not footways):

```
curb_ft = 2 × length_ft − 2 × clearance_ft × (ends) − driveway_allowance
stalls_est = max(curb_ft, 0) / 22
```

- Zero out sides tagged `parking:*=no`.
- Set `metered_flag` / `permit_flag` from city data.
- If you have neither city data nor defensible allowances, **exclude on-street supply** and state it in the memo.

### 7.4 Rates by daypart

Choose one listed rate per facility per daypart. Record the mapping:

| Daypart | Rate used |
|---|---|
| wd_day | Daily or early-bird rate |
| wd_eve, we_eve | Evening flat rate, else hourly × typical evening stay [blank] |
| we_day | Weekend daily rate, else daily |
| event | Event rate, else the highest posted rate |

Put these in `rate_wd_day … rate_event`. Keep `rate_hour`, `rate_day`, `rate_month`, `rate_event` as posted.

**Data reality:** free data rarely has prices. A field survey (signage photos, 20–40 lots across submarkets, recorded with date and observer) is the honest fallback. Mark surveyed rates `capacity_source/rate_source = survey`.

### 7.5 Rate surface (per daypart)

1. **IDW** (Spatial Analyst; QGIS: *IDW interpolation*):
   - Input: facilities with a rate for that daypart
   - Power 2
   - Cell size ≈ 25 m
   - Extent `StudyArea`
   - → `RateSurface_<daypart>`
2. **Cross-validate:** hold out each point (Geostatistical Wizard IDW → Cross Validation). Or manually hold out 20% of points, re-run IDW and compare. Target: mean absolute % error ≤ 20%. Report it.
3. **Zonal Statistics as Table** (mean) by `HexGrid` → `rate_<daypart>` per hex.
4. Compute the rate index:

```
rate_index_d = rate_d / median(rate_d over hexes with data)
```

With fewer than ~8 rate points in a daypart, the surface is unreliable. Say so, and widen the finance sensitivity on rates.

### 7.6 Allocate supply to hexes

1. Effective capacity:
   - public: `capacity_eff = capacity_est`
   - private: `capacity_eff = capacity_est × private_effective_share` (0.50)
2. Run the same OD procedure as 6.4–6.5, with origins = facility points (use the centroid of polygons), cutoff 8 minutes, same band weights, same normalization.
3. Supply is the same across dayparts unless a facility is closed in some dayparts (e.g. office garages closed on weekends). If you know that, set capacity to 0 for those dayparts.
4. Sum by hex → `Analysis/Hex_Supply_Daypart` (`hex_id, daypart, supply_stalls, effective_supply_stalls`).

**Check:** Σ allocated effective supply = Σ facility effective capacity.

---

## 8. Phase D: Gap analysis and hot zones

### 8.1 Gap per hex and daypart

Join demand and supply on `hex_id, daypart` → `Analysis/Hex_Gap_Daypart`:

```
gap_stalls = demand_stalls − effective_supply_stalls
gap_ratio  = demand_stalls / effective_supply_stalls       (if supply = 0: write null, flag as "no supply")
rate_index = from 7.5
```

### 8.2 Hot zones

**Rule:** a hex is hot if `gap_stalls(wd_day) > 0` **and** at least one of `gap_stalls(wd_eve)`, `gap_stalls(we_eve)`, `gap_stalls(event)` is > 0.

1. In a wide table, add `hot_flag` with the rule above.
2. Select `hot_flag = 1` hexes → **Dissolve**.
   - No dissolve field.
   - **Uncheck "Create multipart features."**
   - Adjacent hexes merge into one contiguous zone each.
3. Add fields to `Analysis/HotZones`:
   - `zone_id`
   - `dayparts_positive` (e.g. "wd_day,wd_eve,event")
   - `total_gap_stalls` (sum over its hexes, all dayparts or wd_day, state which)
   - `mean_rate_index`

### 8.3 Checks

- Map M07/M08.
- Hot zones should sit where anchors cluster and supply is thin. If the whole downtown is hot, check whether supply is under-inventoried (missing garages) before believing it.

---

## 9. Phase E: Candidate parcel screen

Evaluate every parcel in the study area. Record **every** failing reason, not just the first.

### 9.1 Pre-compute parcel attributes

| Attribute | How |
|---|---|
| `slope_pct` | *Zonal Statistics as Table* (MEAN; also keep MAX) of `Slope_pct` by parcel |
| `flood_flag` / `floodway_flag` | Intersect with NFHL flood-hazard areas. Floodway: `ZONE_SUBTY` contains "FLOODWAY" [VERIFY field name]. SFHA: `SFHA_TF = 'T'`. |
| `brownfield_flag` | EPA sites within the parcel, or within a small buffer you record |
| `pipeline_flag` | Active building permit or planned development on the parcel (S22) |
| `park/cemetery/ROW` | Land-use code or OSM `leisure=park`, `landuse=cemetery`; ROW parcels (no owner, long thin) |

**Shape index** (method choice; the recommended one is rectangularity):

1. **Minimum Bounding Geometry**: rectangle by area, one per parcel. [QGIS: *Oriented minimum bounding box*]
2. `shape_index = lot_area / rectangle_area`.
3. A square or rectangle scores 1.0; an L or sliver scores low. The 0.60 threshold assumes this metric; log it.

**Frontage:**

1. **Polygon To Line** on parcels.
2. **Buffer** the drive-street centerlines (exclude service/alleys) by `frontage_buffer`.
3. **Intersect** parcel lines with the buffer.
4. Sum length per parcel (in ft) → `frontage_ft`.
5. `arterial_frontage` = 1 if any frontage is on a primary/secondary road.

**Corner flag:** 1 if the parcel fronts on two or more distinct street names (or segments whose bearings differ by ≥ 45°).

**Buildable stalls:**

```
stalls = ROUNDDOWN(lot_sqft × (1 − 0.08) × 0.90 / 320, 0)
```

Example: 40,000 sqft → 103 stalls.

**Walk time to nearest hot zone:** OD cost matrix from parcel centroids to hot-zone hex centroids, cutoff 8 minutes → `walk_min_to_hotzone`. Null if none within 8 minutes.

### 9.2 Apply filters

Add text field `screen_reason`. For each rule a parcel fails, append a code (e.g. `SIZE_MIN;SLOPE`):

| Code | Fails if |
|---|---|
| SIZE_MIN / SIZE_MAX | `lot_sqft` outside min/max |
| STALLS | `stalls` outside 50–300 (see 9.3) |
| SHAPE | `shape_index < 0.60` |
| FRONTAGE | `frontage_ft < 60` |
| LANDUSE | Not Vacant / SurfaceParking / (improvement ratio < 0.25) / auto-oriented commercial (your code list) |
| RES_ZONE | Residential-zoned and zoning doesn't allow commercial parking |
| ZONING | `zoning_screen = Prohibited` |
| FLOODWAY | In floodway |
| SLOPE | `slope_pct ≥ max_slope_pct` |
| EXCLUDED_USE | Park, cemetery, right-of-way |
| PERMIT | Active development permit |
| HOTZONE | Not within 8 minutes of a hot zone |

Then set `screen_status`:

- `Fail` if any code is present
- `Review` if no code but `zoning_screen = Unknown` or a key input is missing (e.g. no assessed value)
- `Pass` otherwise

For Pass parcels write `screen_reason = PASS`. **Pass and Review both continue to scoring**, and Review is flagged.

Save as `Analysis/CandidateParcels`. Include all evaluated parcels, not just passes.

### 9.3 Size vs. stall-range inconsistency (decide and log)

At the default parameters:

| Parcel size | Stalls |
|---|---|
| 15,000 sqft | ~39 |
| ~19,300 sqft | 50 |
| ~116,000 sqft | 300 |
| 200,000 sqft | ~518 |

Recommended: apply **both** the sqft and the stall filters, so the stall range binds. Alternatively, cap stalls at 300 on large parcels (develop part of the site). That is a business choice, so log it.

### 9.4 Candidate count check

SCOPE expects **40–200** Pass + Review candidates.

- If you have fewer, look at which reason code eliminated the most parcels (pivot of `screen_reason`) and consider relaxing that one parameter.
- If you have more, tighten size or walk time.
- Log each change and re-run the screen. Never adjust silently.

---

## 10. Phase F: Network metrics for candidates

For each Pass/Review candidate (use the parcel centroid, or the frontage midpoint if the centroid is far from the street):

1. **Candidate → hex OD matrix**, cutoff 8 minutes → `cand_id, hex_id, minutes`. This defines the hexes inside each candidate's 3/5/8-minute shed and drives C01–C03.
2. **Walk-shed polygons** for maps: *Service Area*, breaks 3, 5, 8, rings not disks → `Analysis/WalkSheds` (`parcel_id, minutes`).
3. **Competitors within 3 minutes:** OD matrix candidates → facilities, cutoff 3 minutes. Sum `capacity_eff`. **Exclude the candidate's own facility** if the parcel is an existing lot.
4. **Top-3 anchors:** OD candidates → anchors, cutoff 15 minutes.
   - Rank anchors reachable from each candidate by total demand (sum of dayparts).
   - Take the top 3 and average their minutes.
   - If fewer than 3 are reachable, use 15 for the missing ones. Log the method.
5. **Population and jobs within 5 minutes:** sum block-group population and block jobs whose centroids fall within 5 minutes (from an OD matrix to those centroids). Used for the memo and context.

---

## 11. Phase G: Criteria, scoring, scenarios, sensitivity

Export a candidate table to `04_excel/Scoring.xlsx` with one row per candidate and the raw measures.

### 11.1 Raw criteria

| ID | Measure (from the candidate's shed tables) | Direction |
|---|---|---|
| C01 | Σ `gap_stalls(wd_day)` over hexes within 5 minutes; if negative, use 0 | Benefit |
| C02 | Σ `gap_stalls(wd_eve + we_day + we_eve)` within 5 minutes; floor 0 | Benefit |
| C03 | Σ `gap_stalls(event)` within 8 minutes × `events_per_year` of venues within 8 minutes (0 if no venue) | Benefit |
| C04 | Rate index at the parcel: weighted mean of daypart rate indices. Weights are a method choice, e.g. equal, or share of operating days; log it. | Benefit |
| C05 | Effective competing stalls within 3 minutes | Cost |
| C06 | Mean walk minutes to the top-3 anchors | Cost |
| C07 | Land cost per buildable stall = land cost (12.3, buy basis) ÷ stalls | Cost |
| C08 | Mean of: corner (0/100), arterial frontage (0/100), AADT percentile of adjacent road (0–100), curb-cut score (manual 0–100 or leave blank → excluded from the mean) | Benefit |
| C09 | ByRight 100, Conditional 60, Unknown 40 | Benefit |
| C10 | Count (or stalls) of planned garages/developments within 5 minutes | Cost |

**Net vs. positive gap:** summing signed hex gaps nets nearby surplus against shortage. That is appropriate because supply was already walk-allocated. Log it.

### 11.2 Normalize (per criterion column, in Excel)

```
p5   = PERCENTILE.INC(col, 0.05)
p95  = PERCENTILE.INC(col, 0.95)
clip = MIN(MAX(x, p5), p95)
s    = IF(p95 = p5, 50, (clip − p5) / (p95 − p5) × 100)
s    = IF(direction = "Cost", 100 − s, s)
```

A constant criterion scores 50 for everyone. Note it in the memo; don't silently drop its weight.

### 11.3 Weighted composite and rank (three scenarios)

1. Put the Appendix B weights in a 3 × 10 table and check each row sums to 1.00.
2. For each scenario:

```
composite = SUMPRODUCT(scores_row, weights_row)          → 0–100
rank      = RANK.EQ(composite, composite_col, 0) + COUNTIFS(composite_col, composite, id_col, "<" & id)
```

The COUNTIFS term breaks ties by parcel ID, so ranks are unique.

Write `SiteScores` (`parcel_id, run_id, scenario, c01_raw…c10_raw, c01_s…c10_s, composite, rank`).

### 11.4 Sensitivity A: One-at-a-time (OAT) ±25%

For each criterion *i* and each scenario:

1. Set `w_i' = w_i × 1.25` (then × 0.75 for the second run).
2. Rescale the other weights so all sum to 1: `w_j' = w_j × (1 − w_i') / (1 − w_i)`.
3. Recompute composites and ranks.
4. Record each site's rank change.

That is 20 runs per scenario. Build them as 20 weight rows and one MMULT (see 11.5).

### 11.5 Sensitivity B: 1,000 random weight draws (flat Dirichlet)

Excel 365 makes this practical:

1. Sheet `Draws`, A2:J1001:

   ```
   =-LN(RAND())
   ```

   Then normalize each row: `K2:T1001 = A2:J2 / SUM(A2:J2)`. These are flat-Dirichlet random weights.
2. **Freeze them:** copy → paste values. This makes the run reproducible; keep this sheet as the "seed" record.
3. Sheet `Scores`: a 10 × N matrix (criteria in rows, candidates in columns) of normalized scores.
4. Composite matrix:

   ```
   =MMULT(Draws!K2:T1001, Scores!B2:?11)
   ```

   This returns 1,000 × N.
5. Rank within each draw row: `=RANK.EQ(cell, row_range, 0)`.
6. Per candidate:
   - `top10_freq = COUNTIF(rank_col, "<=10") / 1000`
   - median rank = `MEDIAN(rank_col)`
   - IQR from `QUARTILE.INC`

**Alternative (log it):** draws centered on a scenario's weights instead of flat. Use gamma draws with shape = κ × w_i; this needs `GAMMA.INV(RAND(), κ×w_i, 1)`.

Output: **rank-stability table** `parcel_id, rank_Balanced, rank_DemandFirst, rank_CostFirst, top10_freq, median_rank, IQR, OAT_max_change`.

---

## 12. Phase H: Financial model (Excel)

Build `Financial_Model.xlsx` with **live formulas** so partners can change inputs.

### 12.1 Workbook layout

| Sheet | Contents |
|---|---|
| `Inputs` | Every finance parameter from the Parameter Sheet as named ranges (e.g. `ConstCostPerStall`, `SoftPct`, `Cap_wd_day`) |
| `Sites` | One row per candidate. Values from GIS: `parcel_id, lot_sqft, stalls, assessed_land, listing_price, gap_ratio_d and gap_stalls_d (5-min shed, each daypart), rate_d (from surface), office_share_wd_day, events_per_year (8-min shed)`. Everything to the right is formulas. |
| `Occupancy` | Curve breakpoints table |
| `CF_Buy`, `CF_Lease` | One row per site, columns Year 0 … Year 10 (+ Year 11 NOI for exit) |
| `Sensitivity` | Shortlisted sites only (12.8) |
| `Summary` | Ranking outputs |

Label every input cell's source (Parameter Sheet row or GIS table) in an adjacent note column.

### 12.2 Occupancy by daypart

This is a method choice; log it. SCOPE says only "f(gap_ratio), capped."

Recommended form:

```
occ_d = MIN( cap_d , g(gap_ratio_d) , capture_share × MAX(gap_stalls_d,0) / stalls )
```

- **g** is a piecewise-linear curve you define in `Occupancy`, e.g. breakpoints (x₁,y₁), (x₂,y₂), (x₃,y₃). **Values blank until set/calibrated.**
- Excel for a 3-point curve:

  ```
  =IF(x<=x1, y1, IF(x<=x2, y1+(x-x1)*(y2-y1)/(x2-x1), IF(x<=x3, y2+(x-x2)*(y3-y2)/(x3-x2), y3)))
  ```

- `gap_ratio` null (no supply) → use `y3`.
- The **absorption term** stops a big lot "filling" from a tiny gap. With 20 unmet stalls, a 300-stall lot can't reach 85%.

### 12.3 Land cost

| Basis | Formula |
|---|---|
| Assessed | `assessed_land_value × assessed_to_market_ratio` |
| Listing | `listing_price` (preferred where present) |
| Ground lease | No purchase. Annual rent = `rent_pct × land_value × (1+escalator)^(t−1)` |

Calibrate `assessed_to_market_ratio` = median of (listing price ÷ assessed land value) across land listings in the market. This needs ≥ 5 listings; otherwise keep the placeholder and flag it [VERIFY].

### 12.4 Development cost

```
construction = stalls × ConstCostPerStall
soft         = construction × SoftPct          (method choice: soft on hard cost; log it)
total_buy    = land + construction + soft
total_lease  = construction + soft
```

Illustrative arithmetic only, with scope placeholders: 103 stalls × $6,500 = $669,500; soft 15% = $100,425.

### 12.5 Revenue (year 1)

**Rates:** `rate_eff_d = rate_d × (1 − new_entrant_rate_discount)`.

**Monthly permits** (optional, office-heavy sites):

```
permit_stalls = IF(office_share_wd_day >= threshold, ROUND(stalls × permit_share,0), 0)
permit_rev    = permit_stalls × rate_month × (1 − discount) × 12
transient_wd_day_stalls = stalls − permit_stalls
```

Permit stalls are also available for evening/weekend use only if your operating model allows it; decide and log.

**Transient revenue per daypart:**

```
rev_d = stalls_d × occ_d × rate_eff_d × units_d × days_d
```

- `units_d` = 1 if daily/flat billing, or billable hours (or turns) if hourly.
- `days_d` = operating days for that daypart.

**Events:**

```
event_days    = events_per_year (venues in 8-min shed; if several venues, sum, noting overlap)
rev_event     = event_days × stalls × occ_event × rate_eff_event
```

To avoid double counting, subtract event days from the evening dayparts they fall on:

- `days_wd_eve −= event_days × weekday_share`
- `days_we_eve −= event_days × (1 − weekday_share)`

**Total:** `gross_revenue = Σ rev_d + rev_event + permit_rev`

### 12.6 Operating costs and NOI (year 1)

```
opex_base   = stalls × OpexPerStall                     (maintenance, insurance, enforcement)
opex_fees   = gross_revenue × (TechFeePct + MgmtFeePct)
prop_tax    = PropTaxRate × (land_value + construction)  (buy; for lease, per lease terms, log)
ground_rent = lease only
NOI         = gross_revenue − opex_base − opex_fees − prop_tax − ground_rent
```

### 12.7 Returns (both tenures)

| Metric | Formula |
|---|---|
| Yield on cost | `NOI₁ / total_cost` |
| Value at cap | `NOI₁ / target_cap_rate` |
| Cash flow year 0 | `−total_cost` |
| Cash flow years 1…10 | `NOI_t = NOI₁ × (1+g_rev)^(t−1)` if you grow NOI as one line. Better: grow revenue and opex separately and recompute each year's NOI. |
| Exit (year 10, buy) | `CF₁₀ += NOI₁₁ / exit_cap × (1 − selling_pct)` |
| Exit (lease) | No land reversion. Improvements valued at 0 at exit unless the lease runs well beyond the hold; log it. |
| IRR | `=IRR(Y0:Y10)` |
| NPV | `=NPV(discount_rate, Y1:Y10) + Y0` (Excel's NPV starts at year 1, so add Y0 separately) |
| Payback | Cumulative CF row. Payback = last negative year + `ABS(cum_prev) / CF_year` of the crossing year. "> hold" if never. |

The model is **unlevered** (no debt). Say so in the memo.

### 12.8 Financial sensitivity (shortlisted sites)

For each shortlisted site, recompute NOI, yield and IRR with one input flexed at a time:

| Input | Flex |
|---|---|
| Occupancy | −15 / +15 percentage points (re-capped at 0–cap) |
| Rates | −20% / +20% |
| Land | −20% / +20% |
| Construction | −15% / +15% |
| Event count | −50% / +50% (range is a method choice; log it) |

Lay out one row per flex with formulas referencing a flexed copy of the inputs. Or use an Excel Data Table, but note Data Tables don't recalculate in some viewers.

**Tornado chart:** bar chart of (IRR_high − base) and (IRR_low − base) per input, sorted by swing.

Write `SiteFinancials` back to GIS (join on `parcel_id`):

- `stalls, land_cost, construction_cost, soft_cost, total_cost`
- `occ_*, rate_*, annual_revenue, opex, noi, yield_on_cost, value_at_cap, payback_years, irr_10yr, npv`
- `tenure`, `sensitivity` (a text summary)

---

## 13. Phase I: Final ranking and shortlist

1. **Financial score:** normalize the chosen metric with the 11.2 method.
   - Recommended metric: yield-on-cost (buy).
   - Alternatives: IRR (buy) or NPV. Log the choice.
2. `final_score = 0.70 × financial_score + 0.30 × Balanced_composite`
3. Rank (unique, tie-break by ID) → `final_rank`.
4. Shortlist the top 5–10 → `Results/Shortlist`.
5. **Recommended site** = rank 1, provided it is top-3 in all three suitability scenarios. If not, explain why in the memo (acceptance criterion 6).
6. **Alternate** = next best that satisfies the same test.
7. Run the scope's Appendix D "shortlist with returns under all scenarios" as a check. In Pro, this is a join of `SiteFinancials` to `SiteScores` then a pivot by scenario.

---

## 14. Phase J: Due-diligence flags

For each shortlisted site, list (don't resolve):

| Flag | Set from |
|---|---|
| Title/ownership | Owner name/type; public or multiple owners → flag |
| Environmental | `brownfield_flag`, EPA sites within 100 m |
| Flood/stormwater | `flood_flag`; impervious-surface stormwater rules → always "confirm with city" |
| Curb cut | Frontage on an arterial / corner position → "confirm access approval" |
| Zoning | Conditional or Unknown → "confirm use permission" |
| Pipeline | Nearby permits/planned garages |
| Tenure | Buy vs. lease IRR difference; landowner willingness unknown |
| Operator/tech | Always listed (payment, LPR/enforcement setup) |

---

## 15. Phase K: Validation and calibration (pilot market)

1. Pick 10–20 existing **paid surface lots** across submarkets.
2. Observe each lot at the peak time of each daypart you can cover (e.g. weekday 11:00, weekday 19:00, Saturday 13:00, Saturday 20:00, one event night).
   - Count occupied stalls: site visit, aerial photo timestamp, or app availability snapshots where terms allow.
   - Record the posted rates.
3. Save to `Observed.xlsx`: `facility_id, daypart, observed_occupancy, observed_rate, date, time, method, observer`.
4. For each lot, compute modeled occupancy with the Phase H formula, treating the lot as a "site". Use its stalls and its 5-minute shed gap, but add its own capacity back into supply-free demand consistently. Log how.
5. Compute errors:
   - `error_pct = (modeled − observed) / observed`
   - Report median absolute error by daypart. Do the same for rates vs. the surface.
6. **Calibrate:**
   - Global per daypart: `factor_d = Σ observed occupied stalls / Σ modeled occupied stalls`.
   - Or per dominant anchor category, if ≥ 3 lots each.
   - Store it in the `ParkingRates.calibration_factor` column and in the Parameter Sheet.
7. Re-run Phases B → I with the factors. **Report calibrated and uncalibrated results side by side.**

Save as the `Validation` table: `run_id, facility_id, observed_metric, observed_value, modeled_value, error_pct`.

---

## 16. QA/QC checklist (record each in `QA_Log.xlsx`)

| Stage | Check | Target |
|---|---|---|
| Ingest | CRS = analysis CRS; extents inside study area | 100% |
| Ingest | Invalid/null geometry; duplicate parcel/facility IDs | 0 |
| Grid | Hexes don't overlap or leave gaps (*Count Overlapping Features*; visual) | 0 |
| Parcels | Overlaps at 0.1 ft tolerance (*Count Overlapping Features*); resolve slivers | 0 material |
| Anchors | Category coverage table; top-50 anchors reviewed | Done |
| Demand | Σ hex demand = Σ anchor demand per daypart | Exact (rounding) |
| Demand | Downtown weekday vs. published study / observed | ±25%, reported |
| Supply | Σ hex supply = Σ effective capacity | Exact |
| Supply | Stated vs. estimated capacity | ≤ 20% |
| Rates | IDW cross-validation error | ≤ 20% |
| Screen | Every evaluated parcel has `screen_reason` | 100% |
| Scoring | Weights sum 1.00; composites 0–100; ranks unique | Exact |
| Sensitivity | Frozen draw sheet saved | Yes |
| Finance | Spot-check 3 sites by hand calculator vs. workbook | Match to $1 |
| Maps | Title, legend, scale, north arrow, sources+vintages, run ID, disclaimer | Every map |
| Package | Every memo number traced to a table cell (keep a trace table) | 100% |

---

## 17. Outputs

### 17.1 Map template (ArcGIS Pro layout)

- **Elements:** market name, run date + run ID, legend, scale bar, north arrow, sources and vintages, parameter version, and the disclaimer: *"Returns are modeled estimates pending due diligence."*
- **Basemap:** Light Gray Canvas for analysis maps; imagery for site maps.
- **Palettes:** sequential for demand/gap; categorical for zoning screen; diverging for scenario differences.
- Save the layout as a `.pagx` and reuse it for every market.

### 17.2 Static maps (PDF + PNG)

| Map | Content |
|---|---|
| M01 | Market context |
| M02 | Anchors by category/size |
| M03–M05 | Demand: wd_day, evening/weekend, event |
| M06 | Supply + rate surface |
| M07–M08 | Gap + hot zones |
| M09 | Screening results with fail-reason inset |
| M10 | Balanced suitability, top 10 labeled |
| M11 | DemandFirst/CostFirst small multiples |
| M12 | Rank stability (top-10 frequency) |
| M13 | Financial ranking by yield |
| M14 | Shortlist with 5-min sheds |
| M15 | Recommended site at 1:2,400 |

### 17.3 Map series

- **MS01 site profiles:** Spatial Map Series, index = `Shortlist`. Dynamic text from `SiteFinancials` for stalls, costs, occupancy/rates, revenue, NOI, yield, IRR, payback, zoning, flags. Add the tornado image per page.
- **MS02:** one page per daypart showing demand, supply and gap side by side. Use three map frames with a daypart definition query driven by the page.

### 17.4 Dashboard

Choose ArcGIS Dashboards (publish the Candidates/Shortlist layers with financial fields) or a simple Excel/Power BI view. Include:

- Scenario and daypart selectors
- Ranked list
- Indicators (stalls, NOI, yield, IRR)
- Top-10 chart
- Occupancy-by-daypart chart
- Due-diligence details

### 17.5 Investment memo (10–15 pages + appendices)

Sections, in order:

1. Executive summary (recommendation, headline returns)
2. Business requirement
3. Market overview
4. Demand
5. Supply and rates
6. Gap and hot zones
7. Screening
8. Scoring and sensitivity
9. Financial model and ranking
10. Shortlist and site profiles
11. Recommendation, risks, due diligence
12. Assumptions and limitations (list every blank you filled and every [VERIFY] still open)
13. Reproducibility (run ID, Parameter Sheet)

Appendices:

- A: sources
- B: rate table + calibration
- C: parameters
- D: QA summary
- E: maps
- F: Excel model

### 17.6 StoryMap

Follow SCOPE §8's 11 sections, using the maps above and the embedded dashboard.

---

## 18. Repeating for the next market

1. Copy the project folder template, Excel workbooks and `.pagx` layouts.
2. New Parameter Sheet: copy the previous one, re-verify regional costs, tax rate, zoning table, land-use crosswalk, rate survey and calibration.
3. Re-download all sources for the new boundary.
4. Run Phases A–J; K if you have observed data.
5. Save the run ID, Parameter Sheet and Decision Log with the package.

---

## Appendix A: Minimum fields per layer

See SCOPE §4.2–4.3. The minimum for a manual run:

| Layer | Fields |
|---|---|
| Parcels | `parcel_id, lot_sqft, land_use_class, zoning_screen, assessed_land_value, assessed_improvement_value, improvement_value_ratio, owner_type` |
| DemandAnchors | `anchor_id, category, size_metric, size_value, dem_* (5)` |
| SupplyFacilities | `facility_id, type, capacity_est, capacity_source, private_flag, capacity_eff, rate_* (5)` |
| Hex_Gap_Daypart | `hex_id, daypart, demand_stalls, effective_supply_stalls, gap_stalls, gap_ratio, rate_index` |
| CandidateParcels | `parcel_id, screen_status, screen_reason, stalls, shape_index, frontage_ft, corner_flag, slope_pct, flood_flag, brownfield_flag, pipeline_flag, walk_min_to_hotzone` |
| SiteScores | `parcel_id, scenario, c01_raw…c10_raw, c01_s…c10_s, composite, rank` |
| SiteFinancials | See 12.8 |
| Shortlist | `parcel_id, final_rank, recommended_flag, alternate_flag, due_diligence_flags` |

## Appendix B: LODES WAC sector → anchor category (starting point [VERIFY] against LODES documentation)

| LODES column | NAICS sector | Suggested category |
|---|---|---|
| C000 | Total jobs | (check sum) |
| CNS07 | Retail trade (44–45) | Retail employment (only if you use a per-employee retail rate; otherwise retail comes from floor area) |
| CNS09–CNS14 | Information; Finance; Real estate; Professional/technical; Management; Admin/support | Office |
| CNS15 | Educational services | University/other, beware double counting with IPEDS |
| CNS16 | Health care | Medical, beware double counting with hospital beds |
| CNS18 | Accommodation and food | Hotel/RestaurantBar staff, usually excluded (covered by room/sqft rates) |
| CNS20 | Public administration | Government → Office rate unless you have another |
| Others (CNS01–06, 08, 17, 19) | Resource, construction, manufacturing, wholesale, transport, arts, other services | Other, include only with a defensible rate |

## Appendix C: Excel formula reference

| Purpose | Formula |
|---|---|
| Stalls | `=ROUNDDOWN(lot_sqft*(1-Setback)*Eff/StallArea,0)` |
| Winsorized 0–100 | `=IF(p95=p5,50,(MIN(MAX(x,p5),p95)-p5)/(p95-p5)*100)` |
| Cost inversion | `=100-s` |
| Unique rank | `=RANK.EQ(x,col,0)+COUNTIFS(col,x,id,"<"&id_cell)` |
| Dirichlet draw (flat) | `=-LN(RAND())` then divide by the row sum; paste values |
| Composite matrix | `=MMULT(weights_1000x10, scores_10xN)` |
| IRR | `=IRR(Y0:Y10)` |
| NPV | `=NPV(rate,Y1:Y10)+Y0` |
| Piecewise occupancy | See 12.2 |

## Appendix D: Observed-data template (`Observed.xlsx`)

`facility_id, name, lat, lon, stalls, daypart, date, time, occupied_count, observed_occupancy, posted_rate, rate_type, method (visit/aerial/app), observer, notes`

## Appendix E: Rate-survey template (`Rates_Observed.xlsx`)

`facility_name, lat, lon, operator, type, rate_hour, rate_day, rate_early_bird, rate_evening, rate_weekend, rate_month, rate_event, observed_date, observer, method (signage/phone/website), photo_ref`

## Appendix F: Admin templates

- **Source Register:** `source_id, provider, dataset, url/endpoint, vintage, download_date, license, native_crs, transformation, notes`
- **Decision Log:** `id, date, phase, question, options considered, choice, rationale, impact, revisit?`
- **Land-use crosswalk:** `county_code, county_description, land_use_class, auto_oriented_commercial (Y/N), notes`
- **Zoning screen table:** `zoning_code, district_name, commercial_parking_use (ByRight/Conditional/Prohibited/Unknown), ordinance_section, notes`

## Appendix G: Decisions you must log in a manual run (checklist)

- [ ] H3 or equal-area hexes
- [ ] Hospital/university vs. LODES double-count rule
- [ ] Restaurant/retail floor-area rule
- [ ] Residential offstreet share (or residential excluded)
- [ ] Mode-share adjustment form and baseline
- [ ] High-frequency transit threshold
- [ ] Large-snap-distance handling
- [ ] Anchor aggregation shortcut (if used)
- [ ] Daypart rate mapping
- [ ] On-street included/excluded
- [ ] Shape-index metric
- [ ] Frontage buffer
- [ ] Size vs. stall-range rule
- [ ] Candidate-count adjustments
- [ ] Net vs. positive gap in C01–C03
- [ ] C04 daypart weights
- [ ] C08 components
- [ ] Dirichlet form
- [ ] Occupancy curve, capture share
- [ ] Billing units and days
- [ ] Event-day overlap split
- [ ] Permit rule
- [ ] Soft-cost base
- [ ] Property-tax base (buy/lease)
- [ ] Exit cap and lease reversion
- [ ] Financial ranking metric
- [ ] Calibration method
