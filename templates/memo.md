# ParkIQ investment memo: {{market_name}}

ParkIQ: A Parking Lot Site Selection Location Intelligence Analysis

**PRIVATE, for partners.** Run `{{run_id}}`, analysis as of {{analysis_month}}. Every number below comes from the run's tables and reports (trace table at the end). Sections marked **[M6]** fill in once the partners set the finance assumptions.

## 1. Executive summary

- **Recommendation:** **[M6]** recommended site and alternate, after underwriting.
- **Where the opportunity is:** {{candidates}} candidate sites pass the screen ({{cand_pass}} outright, {{cand_review}} with a review item); {{top10_east}} of the ten top-ranked sites lie east of North High Street.
- **Biggest shortfall, no sites:** the largest paid-parking shortfall is {{largest_zone_name}} ({{largest_zone_gap}} stalls short on a weekday), but it yields {{largest_zone_candidates}} candidate sites.
- **Headline returns:** **[M6]** yield on cost, 10-year IRR and NPV for the shortlist, buy and ground lease.

## 2. Business requirement

Find parcels in {{market_name}} where a new paid surface parking lot of {{stalls_min}} to {{stalls_max}} stalls would fill across the week and pay, and rank them for acquisition or ground lease.

## 3. Market overview

{{parcels}} parcels on a {{hexes}}-cell H3 grid; {{sources_loaded}} public sources loaded and checked ({{qa_checks}} QA checks, {{qa_errors}} error-level failures; {{sql_checks}} SQL checks, {{sql_failed}} failures).

## 4. Demand analysis

{{anchors}} demand anchors. Modeled demand (stalls): weekday day {{demand_wd_day}}, weekday evening {{demand_wd_eve}}, weekend day {{demand_we_day}}, weekend evening {{demand_we_eve}}. Office demand on weekdays is scaled by an attendance factor of {{attendance_factor}} (hybrid work).

## 5. Supply and rates

{{mapped_facilities}} mapped lots and garages and {{metered_faces}} metered block faces; lots estimated on {{estimated_parcels}} parcels without mapped parking ({{estimated_stalls}} stalls). Rates: **[round-1 and round-2 field survey]**.

## 6. Gap and hot zones

{{paid_hexes}} hexagons have paid parking within an 8-minute walk. {{paid_zones}} paid-parking hot zones ({{paid_zones_50}} short by 50 stalls or more); {{context_zones}} further shortage areas where parking is free (context only).

### Market evidence (City of Columbus Strategic Parking Plan 2019, peak occupancy vs 85 % practical capacity)

{{benchmark_table}}

## 7. Candidate screening

{{within_reach}} sites lie within an 8-minute walk of a paid-parking hot zone. After land use, zoning, size, stalls, shape, frontage, flood, slope and ownership: **{{candidates}} candidates**. {{assemblies}} candidates are assemblies of same-owner parcels, {{existing_only}} are viable only as existing surface lots, {{zone_a}} touch Downtown parking Zone A, and {{owner_flagged}} have public or institutional owners (ground lease possible).

## 8. Suitability scoring and sensitivity

Ten criteria, three weighting scenarios, 1,000 random weightings and one-at-a-time weight changes of 25 %. Rates, venues and planned projects are held neutral until data arrive.

{{top10_table}}

## 9. Financial model and ranking **[M6]**

Buy and ground lease per site: stalls, occupancy and rate by time of week, revenue, operating costs, NOI, yield on cost, value at cap, payback, 10-year IRR and NPV; sensitivity to occupancy, rates, land and construction. Final rank = 70 % financial, 30 % suitability.

## 10. Shortlist and site profiles

See the site profiles in this package (one page per top-ten site). **[M6]** shortlist with returns.

## 11. Recommendation, risks and due-diligence plan

**[M6]** recommendation. Risks and due diligence per site are listed on the profiles (zoning confirmation, legal nonconforming status of existing lots, Zone A/B line, owner, environmental, access).

## 12. Assumptions and limitations

- Demand rates from published parking generation sources, adjusted for local driving and office attendance; calibration against observed counts follows the round-2 survey (M8).
- Supply from mapped lots, estimated lots and metered streets; private lots count at half capacity.
- Finance assumptions: see the partner question sheet (**[partners]**).

## 13. Reproducibility

Run `{{run_id}}`; parameters in `params.yaml`; sources in `data_sources.csv`; every SQL check in `sql_checks.sql`.

## Appendix A. Data sources and vintages

{{sources_table}}

## Appendix B. Parking-rate table and calibration **[M8]**

## Appendix C. Parameters

{{parameters_table}}

## Appendix D. QA summary

{{qa_checks}} QA checks, {{qa_errors}} error-level failures; {{sql_checks}} SQL checks, {{sql_failed}} failures.

## Appendix E. Map gallery

See `maps/` in this package.

## Appendix F. Financial model **[M6]**

`ParkIQ_financial_model_PLACEHOLDER.xlsx` (structure only until M6).

## Number trace

{{trace_table}}
